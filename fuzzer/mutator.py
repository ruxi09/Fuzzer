from dataclasses import dataclass
from typing import Optional, List, Dict, Tuple
import random
import math

from .generator import get_random_clause_len


@dataclass
class MutationFile:
    header: str
    said_atoms: Optional[int]
    said_clauses: Optional[int]
    actual_clauses: int
    lines: List[str]


def change_number_of_clauses(header: str, clauses: int) -> str:
    if random.random() < 0.15:
        return header
    headings = header.split()
    if len(headings) != 4:
        return header
    new_header = headings[:3] + [str(clauses)]
    return " ".join(new_header)


class TestFileMutator:

    def __init__(self, weighted_strategies):
        assert math.isclose(sum(w for (_, w) in weighted_strategies), 1.0), "Weights should add to 1"
        self.weighted_strategies = weighted_strategies

    def mutate_test_file(self, test_file: str, mut_file: MutationFile):
        chosen_strategy = random.choices(*zip(*self.weighted_strategies), k=1)[0]
        with open(test_file, "w") as f:
            f.write(chosen_strategy.mutate(mut_file))


class LineMergerMutatorStrategy:
    """
    Mutates a file by merging lines together.
    """

    def mutate(self, mut_file: MutationFile) -> str:
        delete_first_zero = random.random() < 0.9
        delete_second_zero = random.random() < 0.1

        out = []
        clauses = len(mut_file.lines)
        changes = 0
        i = 0
        while i < len(mut_file.lines):
            # merge 5-40% of the lines  
            if random.random() < 0.10 and i != (len(mut_file.lines) - 1):
                fst = mut_file.lines[i]
                snd = mut_file.lines[i+1]
                if delete_first_zero:
                    fst = fst.rstrip('0').rstrip()
                if delete_second_zero:
                    snd = snd.rstrip('0').rstrip()
                i += 1
                new_line = fst + " " + snd
                changes += 1
                out.append(new_line)
            else:
                out.append(mut_file.lines[i])
            i += 1

        new_header = change_number_of_clauses(mut_file.header, clauses - changes)
        out = [new_header] + out
        return "\n".join(out)


class LineRemoverMutatorStrategy:
    """
    Mutates a file by randomly removing lines.
    """

    def generate_new_line(self, mut_file: MutationFile) -> str:
        if random.random() < 0.5 and (mut_file.said_atoms is not None):
            num_vars = mut_file.said_atoms
        else:
            num_vars = random.randrange(1, 1000)

        clause_len = get_random_clause_len()
        clause = []
        for _ in range(clause_len):
            clause.append(str(random.randint(-num_vars, num_vars)))
        return " ".join(clause)

    def mutate(self, mut_file: MutationFile) -> str:
        remove = random.random() < 0.5
        out = []
        changes = 0
        clauses = len(mut_file.lines)
        for l in mut_file.lines:
            if random.random() > 0.25:
                out.append(l)
                continue
            if remove:
                changes -= 1
                continue
            else:
                changes += 1
                out.append(l)
                out.append(self.generate_new_line(mut_file))

        new_header = change_number_of_clauses(mut_file.header, clauses - changes)
        out = [new_header] + out
        return "\n".join(out)


class AtomChangerMutatorStrategy:
    """
    Mutates files by randomly flipping an atom's sign, removing an atom or adding a new atom.
    """

    def flip_sign(self, atom: str) -> str:
        if atom[0] == '-':
            return atom[1:]
        return "-" + atom

    def new_atom(self) -> str:
        num_vars = str(random.randrange(1, 1000))
        atom = str(num_vars)
        if random.random() < 0.5:
            return "-" + atom
        return atom

    def mutate(self, mut_file: MutationFile) -> str:
        remove = random.random() < 0.5

        out = [mut_file.header]
        for l in mut_file.lines:
            if random.random() < 0.25:
                atoms = l.split(" ")
                new_line = []
                for atom in atoms[:len(atoms) -1]:
                    if len(atom) == 0:
                        continue
                    r = random.random()
                    if r < 0.25: # flip half the atoms
                        new_line.append(self.flip_sign(atom))
                    elif r < 0.5:
                        if remove:
                            # remove atom
                            pass
                        else:
                            new_line.append(atom)
                            new_line.append(self.new_atom())
                    else:
                        new_line.append(atom)
                new_line.append("0")
                out.append(" ".join(new_line))
            else:
                out.append(l)
        return "\n".join(out)


class ByteMutatorStrategy:
    """
    Mutates random bytes in the file.
    """

    def mutate(self, mut_file: MutationFile) -> str:
        lines_bytes = str.encode("\n".join(mut_file.lines))
        out = []
        for b in lines_bytes:
            if random.random() < 0.25:
                b = random.randint(0, 255)
            out.append(b)
        return mut_file.header + bytes(out).decode(errors="ignore")

