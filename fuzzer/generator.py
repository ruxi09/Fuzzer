import random, string, math


def get_random_clause_len() -> int:
    """
    Returns a random clause length for line generation based on a distribution.
    """

    # Some solvers may be prone to not checking the number of operands in the clause
    # so it is worth exercising cases where there are 0 or 1 atoms in the clause.
    CLAUSE_LENGTH_DISTRIBUTION = [(0, 0.005), (1, 0.005), (2, 0.2475), (3, 0.2475), (4, 0.2475), (5, 0.2475)]
    return random.choices(*zip(*CLAUSE_LENGTH_DISTRIBUTION), k=1)[0]


class TestFileGenerator:
    """
    Class to generate test inputs and write them to files.
    """

    def __init__(self, weighted_strategies):
        assert math.isclose(sum(w for (_, w) in weighted_strategies), 1.0), "Weights should add to 1"
        self.weighted_strategies = weighted_strategies

    def generate_test_file(self, test_file: str):
        chosen_strategy = random.choices(*zip(*self.weighted_strategies), k=1)[0]
        with open(test_file, "w") as f:
            f.write(chosen_strategy.generate())

    
class ValidTestGeneratorStrategy:
    """
    Generates a syntactically and semantically valid DIMACS CNF file.
    """

    def generate(self) -> str:
        num_vars = random.randrange(3, 5000)
        num_clauses = random.randrange(3000, 10000)


        header_str = "p cnf {} {}\n".format(num_vars, num_clauses)

        clauses_str = ""
        for c in range(num_clauses):    # NUMBER OF CLAUSES
            clause = []
            clause_len = get_random_clause_len()
            for _ in range(clause_len):    # LENGTH OF EACH CLAUSE
                clause.append(str(random.randint(-num_vars, num_vars)))
            clauses_str += " ".join(clause) + " 0\n"

        return header_str + clauses_str


class InvalidSyntaxTestGeneratorStrategy:
    """
    Generates a slightly syntactically invalid DIMACS CNF file.
    """

    def generate(self) -> str:
        num_vars = random.randrange(3, 5000)
        num_clauses = random.randrange(3000, 10000)

        header_str = "p cnf {} {}\n".format(num_vars, num_clauses)

        clauses_str = ""
        for c in range(num_clauses):    # NUMBER OF CLAUSES
            clause = []
            clause_len = get_random_clause_len()
            for _ in range(clause_len):    # LENGTH OF EACH CLAUSE
                clause.append(str(random.randint(-num_vars, num_vars)))
            clauses_str += " ".join(clause) 
            
            if random.random() < 0.3:
                clauses_str += " 0"
            
            clauses_str += "\n"

        return header_str + clauses_str


class ValidSyntaxInvalidSemanticsTestGeneratorStrategy:
    """
    Generates a syntactically valid but semantically invalid DIMACS CNF file.
    """

    def generate(self) -> str:
        num_vars = self.generate_num_vars()
        if random.random() < 0.1:
            num_vars = self.generate_overflowed_int()

        header_str = "p cnf {} {}\n".format(num_vars, self.generate_num_clauses())

        clauses_str = ""
        for c in range(self.generate_num_clauses()):    # NUMBER OF CLAUSES
            clause = []
            clause_len = get_random_clause_len()
            for _ in range(clause_len):    # LENGTH OF EACH CLAUSE
                clause.append(str(random.randint(-self.generate_num_vars(), self.generate_num_vars())))
            clauses_str += " ".join(clause) + " 0\n"

        return header_str + clauses_str


    def generate_num_clauses(self) -> int:
        return random.randrange(3, 1000)

    def generate_num_vars(self) -> int:
        return random.randrange(3, 5000)

    def generate_overflowed_int(self) -> int:
        MAX_INT = 2147483647
        MIN_INT = -2147483648

        if random.random() < 0.75:
            return random.randrange(MAX_INT + 1, 2 * MAX_INT)
        else:
            return random.randrange(2 * MIN_INT, MIN_INT - 1)


class RandomTestGeneratorStrategy:
    """
    Generates a syntactically invalid file with random garbage bytes.
    """

    def generate(self) -> str:
        header_str = "p cnf {} {}\n".format(self.random_string(), self.random_string())

        clauses_str = ""
        for c in range(random.randrange(0, 100)):
            clauses_str += self.random_string(0, 3) + " "
            if random.random() < 0.5:
                clauses_str += "0"
            
            if random.random() < 0.85:
                clauses_str += "\n"

        return header_str + clauses_str

    def random_char(self) -> str:
        return random.choice(string.printable)

    def random_string(self, min_len: int = 0, max_len: int = 5) -> str:
        s = ""
        for _ in range(random.randint(min_len, max_len)):
            s += self.random_char()
        return s
