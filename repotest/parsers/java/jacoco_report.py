import os
import pandas as pd


def parse_jacoco_report(repo_path: str, source_filename: str) -> dict:
    """
    Parses the JaCoCo HTML report and extracts coverage stats for a given Java source file.
    Args:
        repo_path (str): Path to the repository directory.
        source_filename (str): Name of the source file (e.g., 'Calculator.java').
    Returns:
        dict: A dictionary with coverage stats (e.g., instructions, branches, lines, methods, classes).
    """

    report_path = os.path.join(repo_path, "target", "site", "jacoco", "jacoco.csv")

    if not os.path.exists(report_path):
        # raise FileNotFoundError(f"JaCoCo report not found at {report_path}")
        return None

    df = pd.read_csv(report_path)

    # Get class name from file (strip .java extension)
    target_class = source_filename.replace(".java", "")

    # Find matching row
    match = df[df["CLASS"] == target_class]
    if match.empty:
        # raise ValueError(f"No coverage data found for class '{target_class}'")
        return None

    covered = int(match["INSTRUCTION_COVERED"].values[0])
    missed = int(match["INSTRUCTION_MISSED"].values[0])

    if covered + missed == 0:
        return 0.0

    return covered / (covered + missed)