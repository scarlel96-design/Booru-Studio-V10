from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

PIN = "1.32.9"


def main() -> int:
    try:
        installed = version("gallery-dl")
    except PackageNotFoundError:
        print("gallery-dl: MISSING")
        return 2
    if installed != PIN:
        print(f"gallery-dl: VERSION_MISMATCH expected={PIN} actual={installed}")
        return 3
    from gallery_dl import extractor
    from gallery_dl.job import DataJob
    # Network-free extractor registry check. A stable built-in Danbooru URL must match without
    # performing HTTP; actual site E2E remains a Windows/network release gate.
    matched = extractor.find("https://danbooru.donmai.us/posts/1")
    if matched is None:
        print("gallery-dl: EXTRACTOR_REGISTRY_FAILED")
        return 4
    if DataJob is None:
        return 5
    print(f"gallery-dl: PASS {installed} extractor={matched.category}/{matched.subcategory}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
