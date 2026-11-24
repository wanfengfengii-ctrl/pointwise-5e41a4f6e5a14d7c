"""Raw recording inputs and a full-evidence V1 comparison run."""
from archive import ArtifactCatalog, fetch
from exchange import issue
from record import RevisionStore, freeze
from review import audit
from station import InconsistentConstraints


ALPHA = (
    "alpha", "limited",
    (("s", "S"), ("hidden-shift", None), ("ta", "T"), ("ua", "U"), ("quiet", "I")),
    (("a1", "s", "hidden-shift", 1), ("a2", "hidden-shift", "ta", 1), ("a3", "ta", "ua", 1)),
)
BETA = (
    "beta", "limited", (("sb", "S"), ("tb", "T"), ("ub", "U")),
    (("b2", "sb", "tb", 2), ("b1", "tb", "ub", 1)),
)
GAMMA = (
    "gamma", "limited", (("ug", "U"), ("sg", "S")),
    (("c1", "ug", "sg", -4),),
)
PREFIX_ALPHA = (
    "alpha", "prefix", (("s", "S"), ("hidden-branch", None), ("ta", "T"), ("ua", "U")),
    (("a1", "s", "hidden-branch", 0), ("a8", "hidden-branch", "ta", 1), ("a2", "hidden-branch", "ua", 1)),
)
PREFIX_BETA = (
    "beta", "prefix", (("tb", "T"), ("ub", "U"), ("d", "D")),
    (("b1", "tb", "d", 1), ("b2", "ub", "d", 1)),
)


def freeze_sample(store, sample):
    station, recording, pulse_rows, comparisons = sample
    return freeze(
        store, station, recording,
        [{"name": name, "sync": sync} for name, sync in pulse_rows],
        [{"id": ref, "start": start, "end": end, "upper_us": upper, "unit": "us"}
         for ref, start, end, upper in comparisons],
    )


def full_evidence(samples, queries):
    with RevisionStore(":memory:") as source, ArtifactCatalog(":memory:") as outgoing:
        packages = []
        for sample in samples:
            receipt = issue(source, outgoing, freeze_sample(source, sample))
            packages.append(fetch(outgoing, receipt.artifact_id).payload)
    with ArtifactCatalog(":memory:") as night:
        report, _ = audit(night, packages, queries)
    return [(row.upper_us, [edge.comparison.evidence_id for edge in row.witness]) for row in report.results]


def main():
    cases = [
        ("alpha", [ALPHA], [("S", "U"), ("U", "S"), ("I", "I"), ("S", "I")],
         [(3, ["a1", "a2", "a3"]), (None, []), (0, []), (None, [])]),
        ("alpha+beta", [BETA, ALPHA], [("S", "U"), ("S", "U")], [(3, ["b2", "a3"])] * 2),
        ("shared-reference prefix", [PREFIX_ALPHA, PREFIX_BETA], [("S", "D")], [(2, ["a1", "a2", "b2"])]),
    ]
    for title, samples, queries, expected in cases:
        actual = full_evidence(samples, queries)
        if actual != expected:
            raise AssertionError(f"{title}: expected {expected!r}, got {actual!r}")
        print(f"{title}: {actual}")
    try:
        full_evidence([ALPHA, BETA, GAMMA], [])
    except InconsistentConstraints:
        print("alpha+beta+gamma: inconsistent even with no queries")
    else:
        raise AssertionError("expected whole-batch inconsistency")


if __name__ == "__main__":
    main()
