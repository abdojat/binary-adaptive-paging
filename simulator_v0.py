from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from pathlib import Path
from typing import List, Tuple


# ============================================================
# Basic data structures
# ============================================================

@dataclass(frozen=True)
class Mapping:
    strategy: str
    region_size_pages: int
    virtual_start_page: int
    size_pages: int

    @property
    def virtual_end_page(self) -> int:
        return self.virtual_start_page + self.size_pages


@dataclass(frozen=True)
class Metrics:
    strategy: str
    region_size_pages: int
    mapping_count: int
    avg_mapping_size_pages: float
    largest_mapping_pages: int
    estimated_tlb_reach_pages: int
    internal_fragmentation_pages: int
    lookup_model: str


# ============================================================
# Utility functions
# ============================================================

def msb_position(x: int) -> int:
    """
    Return the position of the most significant set bit.
    Example:
        x = 8  -> 1000b -> returns 3
        x = 4  -> 0100b -> returns 2
        x = 1  -> 0001b -> returns 0
    """
    if x <= 0:
        raise ValueError("msb_position is defined only for positive integers.")
    return x.bit_length() - 1


def binary_decomposition(size_pages: int) -> List[int]:
    """
    Decompose a positive integer into descending powers of two.

    Example:
        13 -> [8, 4, 1]
        19 -> [16, 2, 1]
    """
    if size_pages <= 0:
        raise ValueError("Region size must be positive.")

    chunks: List[int] = []
    for k in range(msb_position(size_pages), -1, -1):
        if size_pages & (1 << k):
            chunks.append(1 << k)
    return chunks


# ============================================================
# Mapping strategies
# ============================================================

def fixed_paging(region_size_pages: int) -> List[Mapping]:
    """
    Fixed-size paging baseline.
    Each base page becomes one mapping.
    """
    return [
        Mapping(
            strategy="fixed",
            region_size_pages=region_size_pages,
            virtual_start_page=i,
            size_pages=1,
        )
        for i in range(region_size_pages)
    ]


def huge_page_mixed(
    region_size_pages: int,
    huge_page_size_pages: int = 512,
) -> List[Mapping]:
    """
    Huge-page-style baseline.

    Assumption:
    - A huge page covers 512 base pages, similar to 2MB huge pages
      when the base page is 4KB.
    - Remainder is mapped using base pages.
    - This is intentionally simple for Simulator v0.
    """
    if region_size_pages <= 0:
        raise ValueError("Region size must be positive.")

    mappings: List[Mapping] = []
    cursor = 0

    while region_size_pages - cursor >= huge_page_size_pages:
        mappings.append(
            Mapping(
                strategy="huge_mixed",
                region_size_pages=region_size_pages,
                virtual_start_page=cursor,
                size_pages=huge_page_size_pages,
            )
        )
        cursor += huge_page_size_pages

    while cursor < region_size_pages:
        mappings.append(
            Mapping(
                strategy="huge_mixed",
                region_size_pages=region_size_pages,
                virtual_start_page=cursor,
                size_pages=1,
            )
        )
        cursor += 1

    return mappings


def binary_adaptive_paging(region_size_pages: int) -> List[Mapping]:
    """
    Binary Adaptive Paging strategy.

    Decompose the region into descending power-of-two chunks.

    Example:
        S = 13
        chunks = [8, 4, 1]
        mappings:
            [0, 8)
            [8, 12)
            [12, 13)
    """
    mappings: List[Mapping] = []
    cursor = 0

    for chunk_size in binary_decomposition(region_size_pages):
        mappings.append(
            Mapping(
                strategy="binary_adaptive",
                region_size_pages=region_size_pages,
                virtual_start_page=cursor,
                size_pages=chunk_size,
            )
        )
        cursor += chunk_size

    assert cursor == region_size_pages
    return mappings


# ============================================================
# XOR/MSB lookup rule
# ============================================================

def bap_lookup(region_size_pages: int, address_offset_page: int) -> Tuple[int, int, int]:
    """
    Binary Adaptive Paging lookup.

    Given:
        S = region_size_pages
        a = address_offset_page

    Rule:
        x = a XOR S
        k = MSB(x)
        chunk_size = 2^k
        chunk_base = S with lower (k+1) bits cleared

    Returns:
        (chunk_base, chunk_size, k)
    """
    S = region_size_pages
    a = address_offset_page

    if S <= 0:
        raise ValueError("Region size must be positive.")
    if not (0 <= a < S):
        raise ValueError("Address offset must satisfy 0 <= a < S.")

    x = a ^ S
    k = msb_position(x)

    chunk_size = 1 << k
    chunk_base = S & ~((1 << (k + 1)) - 1)

    return chunk_base, chunk_size, k


def naive_find_chunk(mappings: List[Mapping], address_offset_page: int) -> Mapping:
    """
    Slow reference implementation.

    This scans the mapping list and returns the mapping containing the address.
    Used only for validation.
    """
    for mapping in mappings:
        if mapping.virtual_start_page <= address_offset_page < mapping.virtual_end_page:
            return mapping

    raise ValueError("Address is not covered by any mapping.")


def validate_bap_lookup(max_region_size_pages: int = 4096) -> None:
    """
    Exhaustively validate the XOR/MSB rule for all region sizes up to max_region_size_pages.

    For each S:
        construct binary_adaptive_paging(S)

    For each address a in [0, S):
        compare:
            - chunk found by bap_lookup(S, a)
            - chunk found by naive boundary scan

    If no assertion fails, the lookup rule is validated for the tested range.
    """
    for S in range(1, max_region_size_pages + 1):
        mappings = binary_adaptive_paging(S)

        for a in range(S):
            chunk_base, chunk_size, _k = bap_lookup(S, a)
            reference = naive_find_chunk(mappings, a)

            assert chunk_base == reference.virtual_start_page, (
                f"Base mismatch: S={S}, a={a}, "
                f"lookup_base={chunk_base}, reference_base={reference.virtual_start_page}"
            )

            assert chunk_size == reference.size_pages, (
                f"Size mismatch: S={S}, a={a}, "
                f"lookup_size={chunk_size}, reference_size={reference.size_pages}"
            )

    print(f"[OK] BAP lookup validated for region sizes 1..{max_region_size_pages} pages.")


# ============================================================
# Metrics
# ============================================================

def estimated_tlb_reach_pages(mappings: List[Mapping], tlb_entries: int) -> int:
    """
    Estimate TLB reach in base pages.

    Simplified model:
    - Assume a TLB has tlb_entries slots.
    - Assume it keeps the largest mappings.
    - Return the total number of base pages covered.

    This is an optimistic upper-bound model, useful for Simulator v0.
    """
    sizes = sorted((m.size_pages for m in mappings), reverse=True)
    return sum(sizes[:tlb_entries])


def compute_metrics(
    strategy: str,
    region_size_pages: int,
    mappings: List[Mapping],
    tlb_entries: int,
) -> Metrics:
    mapping_count = len(mappings)
    largest_mapping = max(m.size_pages for m in mappings)
    avg_mapping_size = region_size_pages / mapping_count

    # In Simulator v0 all strategies map exactly the requested region size.
    # More realistic fragmentation can be added in later versions.
    mapped_pages = sum(m.size_pages for m in mappings)
    internal_fragmentation = mapped_pages - region_size_pages

    if strategy == "fixed":
        lookup_model = "shift/mask; constant-time base-page lookup"
    elif strategy == "huge_mixed":
        lookup_model = "hardware/page-table dependent; huge/base mixed mappings"
    elif strategy == "binary_adaptive":
        lookup_model = "xor + msb + metadata lookup"
    else:
        lookup_model = "unknown"

    return Metrics(
        strategy=strategy,
        region_size_pages=region_size_pages,
        mapping_count=mapping_count,
        avg_mapping_size_pages=avg_mapping_size,
        largest_mapping_pages=largest_mapping,
        estimated_tlb_reach_pages=estimated_tlb_reach_pages(mappings, tlb_entries),
        internal_fragmentation_pages=internal_fragmentation,
        lookup_model=lookup_model,
    )


# ============================================================
# Experiment runner
# ============================================================

def default_region_sizes() -> List[int]:
    """
    A small but useful set of synthetic region sizes in base pages.
    Includes:
    - powers of two
    - one less / one more than powers of two
    - medium and large regions
    """
    return [
        1, 2, 3, 4, 5, 7, 8, 9,
        13, 16, 19, 31, 32, 33,
        63, 64, 65, 127, 128, 129,
        255, 256, 257, 511, 512, 513,
        1000, 1024, 2048, 4096, 8192, 10000,
    ]


def run_experiment(
    region_sizes: List[int],
    tlb_entries: int,
    output_dir: Path,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    rows = []

    for S in region_sizes:
        strategies = {
            "fixed": fixed_paging(S),
            "huge_mixed": huge_page_mixed(S),
            "binary_adaptive": binary_adaptive_paging(S),
        }

        for strategy, mappings in strategies.items():
            metrics = compute_metrics(
                strategy=strategy,
                region_size_pages=S,
                mappings=mappings,
                tlb_entries=tlb_entries,
            )
            rows.append(metrics)

    output_file = output_dir / "summary.csv"

    with output_file.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "strategy",
                "region_size_pages",
                "mapping_count",
                "avg_mapping_size_pages",
                "largest_mapping_pages",
                "estimated_tlb_reach_pages",
                "internal_fragmentation_pages",
                "lookup_model",
            ],
        )
        writer.writeheader()

        for m in rows:
            writer.writerow(
                {
                    "strategy": m.strategy,
                    "region_size_pages": m.region_size_pages,
                    "mapping_count": m.mapping_count,
                    "avg_mapping_size_pages": f"{m.avg_mapping_size_pages:.4f}",
                    "largest_mapping_pages": m.largest_mapping_pages,
                    "estimated_tlb_reach_pages": m.estimated_tlb_reach_pages,
                    "internal_fragmentation_pages": m.internal_fragmentation_pages,
                    "lookup_model": m.lookup_model,
                }
            )

    print(f"[OK] Wrote results to {output_file}")


# ============================================================
# CLI
# ============================================================

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Simulator v0 for Binary Adaptive Paging."
    )

    parser.add_argument(
        "--validate",
        action="store_true",
        help="Run exhaustive validation of XOR/MSB lookup.",
    )

    parser.add_argument(
        "--max-validate-size",
        type=int,
        default=4096,
        help="Maximum region size for exhaustive validation.",
    )

    parser.add_argument(
        "--tlb-entries",
        type=int,
        default=64,
        help="Number of TLB entries in the simplified TLB reach model.",
    )

    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("results"),
        help="Directory where CSV results will be written.",
    )

    return parser.parse_args()


def main() -> None:
    args = parse_args()

    if args.validate:
        validate_bap_lookup(max_region_size_pages=args.max_validate_size)

    run_experiment(
        region_sizes=default_region_sizes(),
        tlb_entries=args.tlb_entries,
        output_dir=args.output_dir,
    )


if __name__ == "__main__":
    main()
