import random, subprocess, os, signal, time, shutil, sys
from dataclasses import dataclass, asdict
from typing import Optional, List, Tuple
from queue import PriorityQueue
from collections import defaultdict, deque
from pathlib import Path

from .coverage import get_run_coverage
from .generator import *
from .mutator import *
from .crash import *

@dataclass
class RunOutput:
    """Class for keeping track of the output of a run."""
    test_file: str
    crash: ProgramCrash
    stderr: str
    coverage: float

    def __hash__(self):
        return hash(frozenset(asdict(self).items()))

    def __lt__(self, other):
        return self.coverage < other.coverage


class Fuzzer:
    """
    The main fuzzer class.
    """

    GENERATION_FUZZING_TIMEOUT: int = 10
    MUTATION_FUZZING_TIMEOUT: int = 40
    CUSTOM_TEST_TIMEOUT: int = 60
    PRE_COVERAGE_PARSING_DELAY: float = 0.25

    TEST_OUTPUT_PATH: str = "fuzzed-tests"
    MAX_SAVED_TESTS: int = 20
    GENERATION_FUZZING_PROB: float = 0.35


    def __init__(self, argv: List[str]):
        """
        Initialise the fuzzer from the supplied arguments and other required state.
        """
        # Get the solver source and executable path
        self.solver_source_path = argv[1]
        self.solver_path = os.path.join("./", self.solver_source_path, "runsat.sh")

        # Get the provided input files
        self.provided_input_tests_path = argv[2]

        # Set the global seed (if provided) for random number generation
        seed = 42
        if len(argv) > 3:
            seed = int(argv[3])
        random.seed(seed)

        # Initialise fuzzer state
        self.generation_strategies = [(ValidTestGeneratorStrategy(), 0.3),
                                      (ValidSyntaxInvalidSemanticsTestGeneratorStrategy(), 0.5),
                                      (InvalidSyntaxTestGeneratorStrategy(), 0.1),
                                      (RandomTestGeneratorStrategy(), 0.1)]
        self.test_file_generator = TestFileGenerator(self.generation_strategies)

        self.mutation_strategies = [(LineMergerMutatorStrategy(), 0.2),
                                    (LineRemoverMutatorStrategy(), 0.2),
                                    (AtomChangerMutatorStrategy(), 0.4),
                                    (ByteMutatorStrategy(), 0.2)]
        self.test_file_mutator = TestFileMutator(self.mutation_strategies)

        self.interesting_cases = defaultdict(ProgramCrash)
        self.work_queue = deque([])
        self.running = False

        # Create the output directory for the saved tests
        if os.path.exists(self.TEST_OUTPUT_PATH):
            try:
                shutil.rmtree(self.TEST_OUTPUT_PATH)
            except OSError:
                print("Could not delete directory (probably due to a file lock), continuing with previous contents")
        os.makedirs(self.TEST_OUTPUT_PATH, exist_ok=True)


    def start(self):
        """
        Run the main fuzzer loop.
        """

        print(f"Running fuzzer against SUT in {self.solver_source_path}")

        # This is needed so LabTS does not complain about missing files in case the fuzzer
        # does not generate enough test files in 180 seconds. These files are removed as the
        # real test files are generated.
        # We are assuming that the marking itself is done with the 30-min timeout
        # and signaled via a SIGTERM (at which point our output will be saved)
        for i in range(self.MAX_SAVED_TESTS):
            self.test_file_generator.generate_test_file(os.path.join(self.TEST_OUTPUT_PATH, f"dummy_{i}.cnf"))

        self.running = True

        # Run the provided inputs first
        self.run_provided_inputs_phase(self.provided_input_tests_path)

        # Run a hybrid of generation and mutation strategies
        curr_iter = 0
        while self.running:
            curr_iter += 1
            self.print_progress(curr_iter)

            try:
                if random.random() < self.GENERATION_FUZZING_PROB:
                    self.generation_fuzzing(curr_iter)
                else:
                    self.mutation_fuzzing(curr_iter)
            except Exception as e:
                print("Exception occurred during fuzzing:", str(type(e)))


    def run_provided_inputs_phase(self, inputs_path: str):
        """
        Run the inputs in the provided directory against the SUT.
        """

        with os.scandir(inputs_path) as it:
            for entry in it:
                if entry.name.endswith(".cnf") and entry.is_file():
                    _, stderr, _ = self.run_solver(self.solver_path, entry.path, self.CUSTOM_TEST_TIMEOUT)

                    time.sleep(self.PRE_COVERAGE_PARSING_DELAY)

                    # Get the run output status (and discard if the run was not interesting)
                    dest_file = os.path.join(self.TEST_OUTPUT_PATH, entry.name)
                    run_output = self.get_run_output(dest_file, stderr)
                    if run_output is None:
                        continue
                    
                    # Add the crash to the sorted queue of interesting cases (sorted by coverage)
                    if run_output.crash not in self.interesting_cases:
                        self.interesting_cases[run_output.crash] = PriorityQueue()
                        self.work_queue.append(run_output)

                    self.interesting_cases[run_output.crash].put((-run_output.coverage, run_output))

                    # Write to directory
                    shutil.copy(entry.path, dest_file)
                    self.clean_dummy_files()


    def generation_fuzzing(self, curr_iter: int):
        """
        Generate a file from scratch using a generative strategy and run the solver
        against the generated input.
        """

        # Produce a test input file for the fuzzer
        test_file = "test_input.cnf"
        self.test_file_generator.generate_test_file(test_file)

        # Run the fuzzer against the input file
        _, stderr, _ = self.run_solver(self.solver_path, test_file)

        time.sleep(self.PRE_COVERAGE_PARSING_DELAY)

        # Get the run output status (and discard if the run was not interesting)
        dest_file = os.path.join(self.TEST_OUTPUT_PATH, f"crashing_test_{curr_iter}.cnf")
        run_output = self.get_run_output(dest_file, stderr)
        if run_output is None:
            return

        # Add the crash to the sorted queue of interesting cases (sorted by coverage)
        if run_output.crash not in self.interesting_cases:
            self.work_queue.append(run_output)
            self.interesting_cases[run_output.crash] = PriorityQueue()

        self.interesting_cases[run_output.crash].put((-run_output.coverage, run_output))

        shutil.move(test_file, dest_file)
        self.clean_dummy_files()


    def mutation_fuzzing(self, curr_iter: int):
        """
        Performs mutation-based fuzzing by choosing the next interesting file on the
        work queue.
        """

        if len(self.work_queue) == 0:
            return

        # Get the next interesting test case from the queue and mutate it
        case_to_mutate = self.work_queue.popleft()

        with open(case_to_mutate.test_file) as f:
            lines = f.read().split("\n")
            try:
                self.mutate(lines, curr_iter, case_to_mutate)
            except Exception as e:
                print("Exception during mutation", str(type(e)), " - Skipping to next iteration")

    def is_interesting_mutation(self, before: RunOutput, after: RunOutput) -> Tuple[bool, bool]:
        """
        Checks if the mutation is interesting and whether it should be kept in the
        work queue of mutations.
        """
        
        if after.crash not in self.interesting_cases:
            # new mutation, add both after and before to the queue
            return (True, True)
        if after.crash != before.crash:
            # We discovered a new error, so keep both
            return (True, True)
        elif after.coverage > before.coverage:
            # We got the same error, but with higher coverage, so keep after
            # and discard before
            return (True, False)

        # Uninteresting, just keep before
        return (False, True)


    def mutate(self, lines: List[str], curr_iter: int, before: RunOutput):
        """
        Performs a mutation on the input lines given.
        """

        if len(lines) < 2:
            return

        header = lines[0]
        headings = header.split()
        if len(headings) != 4:
            return

        said_atoms, said_clauses = headings[2], headings[3]
        actual_clauses = len(lines) - 1
        try:
            said_atoms = int(said_atoms)
            said_clauses = int(said_clauses)
        except:
            said_atoms, said_clauses = None, None

        mut_file = MutationFile(header, said_atoms, said_clauses, actual_clauses, lines[1:])
        
        test_file = "test_input.cnf"
        self.test_file_mutator.mutate_test_file(test_file, mut_file)

        _, stderr, _ = self.run_solver(self.solver_path, test_file, self.MUTATION_FUZZING_TIMEOUT)

        time.sleep(self.PRE_COVERAGE_PARSING_DELAY)

        # Get the run output status (and discard if the run was not interesting)
        dest_file = os.path.join(self.TEST_OUTPUT_PATH, f"crashing_test_{curr_iter}.cnf")
        run_output = self.get_run_output(dest_file, stderr)
        if run_output is None:
            return

        # Add the crash to the sorted queue of interesting cases (sorted by coverage)
        if run_output.crash not in self.interesting_cases:
            self.interesting_cases[run_output.crash] = PriorityQueue()
        
        keep_after, keep_before = self.is_interesting_mutation(run_output, before)
        if keep_after:
            self.work_queue.append(run_output)
        if keep_before:
            self.work_queue.append(before)

        self.interesting_cases[run_output.crash].put((-run_output.coverage, run_output))

        # Write to directory
        shutil.copy(test_file, dest_file)
        self.clean_dummy_files()


    def get_run_output(self, test_file: str, stderr: str) -> Optional[RunOutput]:
        """
        Given the stderr output of the run, gather all the crash and coverage data.
        Returns None if the program did not crash.
        """

        # Get the program crash information
        program_crash = analyse_program_crash(stderr)
        if program_crash is None:
            return None
        # Get the coverage information from the run
        total_cov_pcntg = get_run_coverage(self.solver_source_path)
        return RunOutput(test_file, program_crash, stderr, total_cov_pcntg)


    def run_solver(self, solver: str, test_file: str, timeout: int = 10) -> RunOutput:
        """
        Runs the SAT solver on the given test file.
        """
        
        # Run the solver as a subprocess
        cmd = f"{solver} {test_file}"
        proc = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        
        # Wait for the subprocess to finish or timeout
        start_time = time.time()
        while True:
            if proc.poll() is not None:
                break
            if time.time() - start_time > timeout:
                proc.send_signal(signal.SIGTERM)
                break

        # Get the output
        try:
            stdout, stderr = proc.communicate(timeout=0.5)
        except subprocess.TimeoutExpired:
            return "", "", 0
        return stdout.decode(errors="ignore"), stderr.decode(errors="ignore"), proc.returncode


    def shutdown(self):
        """
        Stop the fuzzer and save the interesting inputs to the directory
        """

        self.running = False
        print("\n\nShutting down fuzzer, saving the best files to disk")
        keep = []
        saved = 0
        to_save = min(self.MAX_SAVED_TESTS, self.total_num_crashes())
        print(f"Saving {to_save} tests to output directory")
        while saved < to_save:
            for _, pq in self.interesting_cases.items():
                if saved == to_save:
                    break
                if pq.empty():
                    continue
                run_output = pq.get()[1]
                keep.append(Path(run_output.test_file).name)
                saved += 1
        
        print("Keeping", keep)
        self.clean_files_on_shutdown(keep)
        print("---------- FUZZER FINISHED ----------")
        sys.exit(0)


    def clean_files_on_shutdown(self, keep: List[str]):
        """
        Deletes all files in the outpat path that are not in the given list.
        """
        with os.scandir(self.TEST_OUTPUT_PATH) as it:
            for entry in it:
                if entry.name not in keep:
                    try:
                        os.remove(entry.path)
                    except FileNotFoundError:
                        pass
    

    def clean_dummy_files(self, remove_single_file: bool = True):
        """
        Cleans the dummy files generated at the start.
        """

        with os.scandir(self.TEST_OUTPUT_PATH) as it:
            for entry in it:
                if entry.name.startswith("dummy_") and entry.name.endswith(".cnf") and entry.is_file():
                    try:
                        os.remove(entry.path)
                    except:
                        pass
                    if remove_single_file:
                        break


    def total_num_crashes(self) -> int:
        """
        Returns the total number of inputs found to cause a crash.
        """

        total = 0
        for _, pq in self.interesting_cases.items():
            total += pq.qsize()
        return total


    def print_progress(self, curr_iter: int):
        freq = 100

        if curr_iter < 10:
            freq = 1
        elif curr_iter < 100:
            freq = 10
        elif curr_iter > 1000:
            freq = 500

        if curr_iter % freq == 0:
            print(f"Iteration {curr_iter}: distinct crash types found {len(self.interesting_cases.keys())}, total crashes found: {self.total_num_crashes()}")
