from scripts.benchmark_atena_capabilities import TASKS, score


def task(task_id):
    return next(item for item in TASKS if item.task_id == task_id)


def test_gaussian_accepts_equivalent_notation():
    result = score(task("math-gaussian"), "A integral converge e vale sqrt(pi), aproximadamente 1.7724538509, por coordenadas polares.")
    assert result["passed"] is True
    assert result["symbolic_check"]["method"] == "sympy"


def test_series_accepts_pi_squared_over_six():
    result = score(task("math-series"), "A série converge pelo teste p e vale pi^2/6.")
    assert result["passed"] is True
    assert result["symbolic_check"]["equivalent"] is True


def test_linear_solution_is_checked_by_substitution():
    result = score(task("math-linear"), "Por eliminação, x = 2 e y = 1; substituindo, o sistema é satisfeito.")
    assert result["passed"] is True
    assert result["symbolic_check"]["equivalent"] is True


def test_linear_wrong_solution_is_rejected():
    result = score(task("math-linear"), "A solução é x = 3 e y = 2.")
    assert result["passed"] is False
    assert result["symbolic_check"]["equivalent"] is False
