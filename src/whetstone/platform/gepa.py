"""The GEPA wrapper: the only module that imports GEPA, reached through gepa.optimize and this adapter only."""

from collections.abc import Callable, Mapping, Sequence
from typing import Any

from gepa.api import optimize as gepa_optimize  # pyright: ignore[reportUnknownVariableType]  # GEPA types its result loosely
from gepa.core.adapter import EvaluationBatch, GEPAAdapter

# A version's text and a batch of case ids -> per case: score, feedback, the input and the output GEPA reflects on.
Evaluate = Callable[[str, list[str]], list[tuple[float, str, Any, Any]]]
COMPONENT = "editable"


class _Adapter(GEPAAdapter[str, dict[str, Any], Any]):
    # Subclassing GEPAAdapter, not only matching its shape: an adapter that didn't made every rewrite fail silently.
    def __init__(self, evaluate: Evaluate) -> None:
        self._evaluate = evaluate

    def evaluate(self, batch: list[str], candidate: dict[str, str], capture_traces: bool = False) -> EvaluationBatch[dict[str, Any], Any]:
        results = self._evaluate(candidate[COMPONENT], batch)
        traces = [{"input": r[2], "output": r[3], "feedback": r[1]} for r in results]
        return EvaluationBatch(outputs=[r[3] for r in results], scores=[r[0] for r in results], trajectories=traces if capture_traces else None)

    def make_reflective_dataset(
        self, candidate: dict[str, str], eval_batch: EvaluationBatch[dict[str, Any], Any], components_to_update: list[str]
    ) -> Mapping[str, Sequence[Mapping[str, Any]]]:
        rows = [{"Inputs": t["input"], "Generated Outputs": t["output"], "Feedback": t["feedback"]} for t in eval_batch.trajectories or []]
        return {component: rows for component in components_to_update}


def optimize(seed: str, train: list[str], select: list[str], evaluate: Evaluate, reflect: Callable[[str], str], budget: int, stop: Callable[[], bool]) -> None:
    """Runs GEPA until `budget` generations are spent or `stop()` says so. GEPA picks which versions to try;
    `evaluate` sees every one, so the caller keeps its own record of them."""
    def stopper(gepa_state: Any) -> bool:
        return stop()

    gepa_optimize(
        seed_candidate={COMPONENT: seed},
        trainset=train,
        valset=select,
        adapter=_Adapter(evaluate),
        reflection_lm=lambda prompt: reflect(prompt if isinstance(prompt, str) else "\n\n".join(str(m["content"]) for m in prompt)),
        reflection_minibatch_size=3,
        max_metric_calls=budget,
        stop_callbacks=[stopper],
        raise_on_exception=True,
    )
