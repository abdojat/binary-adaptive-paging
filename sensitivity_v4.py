from __future__ import annotations

import argparse
import csv
import importlib.util
import statistics
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Sequence

import matplotlib.pyplot as plt


# ============================================================
# Sensitivity analysis v4 for Binary Adaptive Paging
# ============================================================
#
# This script is intended to be placed next to:
#   simulator_v3_workloads.py
#
# It imports the v3 simulator and runs parameter sweeps over:
#   - max_bap_chunk_pages
#   - split_density_threshold
#   - random seeds
#
# Why this matters:
#   Simulator v3 showed useful workload-aware behavior, but it used one
#   parameter setting. A reviewer may ask whether the conclusions hold only
#   for max_chunk=512, threshold=0.25, or seed=42.
#
# This script produces:
#   results_v4_sensitivity/sensitivity_summary_v4.csv
#   results_v4_sensitivity/sensitivity_aggregated_v4.csv
#   results_v4_sensitivity/plots/max_chunk_fault_amplification_v4.png
#   results_v4_sensitivity/plots/threshold_split_tradeoff_v4.png
#   results_v4_sensitivity/plots/max_chunk_mapping_count_v4.png
#
# Recommended command:
#   python sensitivity_v4.py --simulator-path simulator_v3_workloads.py


@dataclass(frozen=True)
class AggregatedRow:
    max_bap_chunk_pages: int
    split_density_threshold: float
    strategy: str
    workload: str
    region_size_pages: int
    mean_mapping_count: float
    mean_fault_amplification_no_split: float
    mean_fault_amplification_after_split: float
    mean_adaptive_split_added_entries: float
    mean_permission_refined_mapping_count: float


def load_simulator(simulator_path: Path):
    if not simulator_path.exists():
        raise FileNotFoundError(
            f"Cannot find {simulator_path}. Put this script next to simulator_v3_workloads.py "
            "or pass --simulator-path."
        )

    spec = importlib.util.spec_from_file_location("simulator_v3_workloads", simulator_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot import simulator from {simulator_path}")

    module = importlib.util.module_from_spec(spec)

    # Important fix:
    # dataclasses expect the dynamically imported module to be present in sys.modules
    # while the class decorators are executed. Without this, Python 3.12 can raise:
    # AttributeError: 'NoneType' object has no attribute '__dict__'
    import sys
    sys.modules[spec.name] = module

    spec.loader.exec_module(module)
    return module


def mean(values: Sequence[float]) -> float:
    if not values:
        return 0.0
    return float(statistics.mean(values))


def write_csv(path: Path, rows: List[dict], fieldnames: Sequence[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def aggregate(raw_rows: List[dict]) -> List[AggregatedRow]:
    grouped: Dict[tuple, List[dict]] = {}

    for row in raw_rows:
        key = (
            row["max_bap_chunk_pages"],
            row["split_density_threshold"],
            row["strategy"],
            row["workload"],
            row["region_size_pages"],
        )
        grouped.setdefault(key, []).append(row)

    aggregated: List[AggregatedRow] = []

    for key, group in sorted(grouped.items()):
        max_chunk, threshold, strategy, workload, region_size = key

        aggregated.append(
            AggregatedRow(
                max_bap_chunk_pages=int(max_chunk),
                split_density_threshold=float(threshold),
                strategy=strategy,
                workload=workload,
                region_size_pages=int(region_size),
                mean_mapping_count=mean([float(r["mapping_count"]) for r in group]),
                mean_fault_amplification_no_split=mean(
                    [float(r["fault_amplification_no_split"]) for r in group]
                ),
                mean_fault_amplification_after_split=mean(
                    [float(r["fault_amplification_after_adaptive_split"]) for r in group]
                ),
                mean_adaptive_split_added_entries=mean(
                    [float(r["adaptive_split_added_entries"]) for r in group]
                ),
                mean_permission_refined_mapping_count=mean(
                    [float(r["permission_refined_mapping_count"]) for r in group]
                ),
            )
        )

    return aggregated


def plot_max_chunk_fault_amplification(
    aggregated: List[AggregatedRow],
    output_file: Path,
    workload: str = "sparse_random",
    threshold: float = 0.25,
    region_size_pages: int = 10000,
) -> None:
    strategies = [
        "binary_adaptive_limited",
        "binary_adaptive_unbounded",
        "multi_size_aligned",
        "fixed",
    ]

    plt.figure(figsize=(9.5, 5.4))

    for strategy in strategies:
        data = sorted(
            [
                r for r in aggregated
                if r.workload == workload
                and r.split_density_threshold == threshold
                and r.region_size_pages == region_size_pages
                and r.strategy == strategy
            ],
            key=lambda r: r.max_bap_chunk_pages,
        )

        if not data:
            continue

        plt.plot(
            [r.max_bap_chunk_pages for r in data],
            [r.mean_fault_amplification_no_split for r in data],
            marker="o",
            label=strategy,
        )

    plt.xscale("log", base=2)
    plt.xlabel("Maximum BAP chunk size (base pages, log2 scale)")
    plt.ylabel("Mean fault amplification before split")
    plt.title(f"Chunk-size sensitivity before split: {workload}")
    plt.grid(True, which="both", linewidth=0.5)
    plt.legend()
    plt.tight_layout()

    output_file.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(output_file, dpi=220)
    plt.close()


def plot_threshold_split_tradeoff(
    aggregated: List[AggregatedRow],
    output_file: Path,
    strategy: str = "binary_adaptive_limited",
    workload: str = "hot_cold_clustered",
    max_chunk: int = 512,
    region_size_pages: int = 10000,
) -> None:
    data = sorted(
        [
            r for r in aggregated
            if r.strategy == strategy
            and r.workload == workload
            and r.max_bap_chunk_pages == max_chunk
            and r.region_size_pages == region_size_pages
        ],
        key=lambda r: r.split_density_threshold,
    )

    thresholds = [r.split_density_threshold for r in data]
    amplification = [r.mean_fault_amplification_after_split for r in data]
    added_entries = [r.mean_adaptive_split_added_entries for r in data]

    fig, ax1 = plt.subplots(figsize=(9.5, 5.4))

    ax1.plot(thresholds, amplification, marker="o", label="Amplification after split")
    ax1.set_xlabel("Split density threshold")
    ax1.set_ylabel("Mean amplification after split")
    ax1.grid(True, which="both", linewidth=0.5)

    ax2 = ax1.twinx()
    ax2.plot(thresholds, added_entries, marker="s", label="Added split entries")
    ax2.set_ylabel("Mean added mapping entries")

    lines_1, labels_1 = ax1.get_legend_handles_labels()
    lines_2, labels_2 = ax2.get_legend_handles_labels()
    ax1.legend(lines_1 + lines_2, labels_1 + labels_2, loc="best")

    plt.title(f"Split-threshold tradeoff: {strategy}, {workload}")
    fig.tight_layout()

    output_file.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(output_file, dpi=220)
    plt.close()


def plot_max_chunk_mapping_count(
    aggregated: List[AggregatedRow],
    output_file: Path,
    threshold: float = 0.25,
    workload: str = "dense_sequential",
    region_size_pages: int = 10000,
) -> None:
    strategies = [
        "binary_adaptive_limited",
        "binary_adaptive_unbounded",
        "multi_size_aligned",
        "fixed",
    ]

    plt.figure(figsize=(9.5, 5.4))

    for strategy in strategies:
        data = sorted(
            [
                r for r in aggregated
                if r.workload == workload
                and r.split_density_threshold == threshold
                and r.region_size_pages == region_size_pages
                and r.strategy == strategy
            ],
            key=lambda r: r.max_bap_chunk_pages,
        )

        if not data:
            continue

        plt.plot(
            [r.max_bap_chunk_pages for r in data],
            [r.mean_mapping_count for r in data],
            marker="o",
            label=strategy,
        )

    plt.xscale("log", base=2)
    plt.yscale("log")
    plt.xlabel("Maximum BAP chunk size (base pages, log2 scale)")
    plt.ylabel("Mean mapping entries (log scale)")
    plt.title("Mapping-count sensitivity to maximum chunk size")
    plt.grid(True, which="both", linewidth=0.5)
    plt.legend()
    plt.tight_layout()

    output_file.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(output_file, dpi=220)
    plt.close()


def run_sensitivity(
    simulator,
    output_dir: Path,
    max_bap_chunks: Sequence[int],
    thresholds: Sequence[float],
    seeds: Sequence[int],
    tlb_entries: int,
    max_page_size_pages: int,
    huge_page_size_pages: int,
) -> None:
    raw_rows: List[dict] = []

    # Keep v4 focused and cheap.
    region_sizes = [10000]
    region_starts = [0]
    selected_workloads = [
        "dense_sequential",
        "sparse_random",
        "very_sparse_random",
        "hot_cold_clustered",
        "cow_burst",
        "mixed_permissions",
    ]

    for max_chunk in max_bap_chunks:
        for threshold in thresholds:
            for seed in seeds:
                results = simulator.run_experiment(
                    region_sizes=region_sizes,
                    region_starts=region_starts,
                    max_page_size_pages=max_page_size_pages,
                    max_bap_chunk_pages=max_chunk,
                    huge_page_size_pages=huge_page_size_pages,
                    tlb_entries=tlb_entries,
                    split_density_threshold=threshold,
                    seed=seed,
                    output_dir=output_dir / "_tmp_runs" / f"chunk_{max_chunk}_thr_{threshold}_seed_{seed}",
                    make_plot_files=False,
                )

                for r in results:
                    if r.workload not in selected_workloads:
                        continue

                    raw_rows.append(
                        {
                            "max_bap_chunk_pages": max_chunk,
                            "split_density_threshold": threshold,
                            "seed": seed,
                            "strategy": r.strategy,
                            "workload": r.workload,
                            "region_start_page": r.region_start_page,
                            "region_size_pages": r.region_size_pages,
                            "mapping_count": r.mapping_count,
                            "largest_mapping_pages": r.largest_mapping_pages,
                            "estimated_tlb_reach_pages": r.estimated_tlb_reach_pages,
                            "touched_pages": r.touched_pages,
                            "loaded_pages_no_split": r.loaded_pages_no_split,
                            "fault_amplification_no_split": f"{r.fault_amplification_no_split:.6f}",
                            "adaptive_mapping_count": r.adaptive_mapping_count,
                            "adaptive_split_added_entries": r.adaptive_split_added_entries,
                            "loaded_pages_after_adaptive_split": r.loaded_pages_after_adaptive_split,
                            "fault_amplification_after_adaptive_split": f"{r.fault_amplification_after_adaptive_split:.6f}",
                            "permission_refined_mapping_count": r.permission_refined_mapping_count,
                            "permission_split_added_entries": r.permission_split_added_entries,
                        }
                    )

    raw_fields = [
        "max_bap_chunk_pages",
        "split_density_threshold",
        "seed",
        "strategy",
        "workload",
        "region_start_page",
        "region_size_pages",
        "mapping_count",
        "largest_mapping_pages",
        "estimated_tlb_reach_pages",
        "touched_pages",
        "loaded_pages_no_split",
        "fault_amplification_no_split",
        "adaptive_mapping_count",
        "adaptive_split_added_entries",
        "loaded_pages_after_adaptive_split",
        "fault_amplification_after_adaptive_split",
        "permission_refined_mapping_count",
        "permission_split_added_entries",
    ]

    write_csv(output_dir / "sensitivity_summary_v4.csv", raw_rows, raw_fields)

    aggregated = aggregate(raw_rows)

    aggregated_rows = [
        {
            "max_bap_chunk_pages": r.max_bap_chunk_pages,
            "split_density_threshold": r.split_density_threshold,
            "strategy": r.strategy,
            "workload": r.workload,
            "region_size_pages": r.region_size_pages,
            "mean_mapping_count": f"{r.mean_mapping_count:.4f}",
            "mean_fault_amplification_no_split": f"{r.mean_fault_amplification_no_split:.6f}",
            "mean_fault_amplification_after_split": f"{r.mean_fault_amplification_after_split:.6f}",
            "mean_adaptive_split_added_entries": f"{r.mean_adaptive_split_added_entries:.4f}",
            "mean_permission_refined_mapping_count": f"{r.mean_permission_refined_mapping_count:.4f}",
        }
        for r in aggregated
    ]

    aggregated_fields = [
        "max_bap_chunk_pages",
        "split_density_threshold",
        "strategy",
        "workload",
        "region_size_pages",
        "mean_mapping_count",
        "mean_fault_amplification_no_split",
        "mean_fault_amplification_after_split",
        "mean_adaptive_split_added_entries",
        "mean_permission_refined_mapping_count",
    ]

    write_csv(output_dir / "sensitivity_aggregated_v4.csv", aggregated_rows, aggregated_fields)

    plot_dir = output_dir / "plots"

    plot_max_chunk_fault_amplification(
        aggregated,
        plot_dir / "max_chunk_fault_amplification_v4.png",
        workload="sparse_random",
        threshold=0.25,
    )

    plot_threshold_split_tradeoff(
        aggregated,
        plot_dir / "threshold_split_tradeoff_v4.png",
        strategy="binary_adaptive_limited",
        workload="hot_cold_clustered",
        max_chunk=512,
    )

    plot_max_chunk_mapping_count(
        aggregated,
        plot_dir / "max_chunk_mapping_count_v4.png",
        threshold=0.25,
    )

    print(f"[OK] Wrote raw sensitivity results: {output_dir / 'sensitivity_summary_v4.csv'}")
    print(f"[OK] Wrote aggregated sensitivity results: {output_dir / 'sensitivity_aggregated_v4.csv'}")
    print(f"[OK] Wrote plots under: {plot_dir}")


def parse_int_list(text: str) -> List[int]:
    return [int(x.strip()) for x in text.split(",") if x.strip()]


def parse_float_list(text: str) -> List[float]:
    return [float(x.strip()) for x in text.split(",") if x.strip()]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Sensitivity analysis v4 for Binary Adaptive Paging."
    )

    parser.add_argument(
        "--simulator-path",
        type=Path,
        default=Path("simulator_v3_workloads.py"),
        help="Path to simulator_v3_workloads.py.",
    )

    parser.add_argument(
        "--max-bap-chunks",
        type=str,
        default="128,256,512,1024,2048",
        help="Comma-separated max BAP chunk sizes in base pages.",
    )

    parser.add_argument(
        "--thresholds",
        type=str,
        default="0.05,0.1,0.25,0.5",
        help="Comma-separated split density thresholds.",
    )

    parser.add_argument(
        "--seeds",
        type=str,
        default="1,2,3,4,5",
        help="Comma-separated random seeds.",
    )

    parser.add_argument(
        "--tlb-entries",
        type=int,
        default=64,
        help="TLB entries for the simplified TLB reach model.",
    )

    parser.add_argument(
        "--max-page-size-pages",
        type=int,
        default=512,
        help="Maximum page size for multi-size baselines.",
    )

    parser.add_argument(
        "--huge-page-size-pages",
        type=int,
        default=512,
        help="Huge-page size for huge_mixed baseline.",
    )

    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("results_v4_sensitivity"),
        help="Output directory.",
    )

    return parser.parse_args()


def main() -> None:
    args = parse_args()

    simulator = load_simulator(args.simulator_path)

    run_sensitivity(
        simulator=simulator,
        output_dir=args.output_dir,
        max_bap_chunks=parse_int_list(args.max_bap_chunks),
        thresholds=parse_float_list(args.thresholds),
        seeds=parse_int_list(args.seeds),
        tlb_entries=args.tlb_entries,
        max_page_size_pages=args.max_page_size_pages,
        huge_page_size_pages=args.huge_page_size_pages,
    )


if __name__ == "__main__":
    main()
