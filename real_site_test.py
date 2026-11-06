#!/usr/bin/env python3
"""
Real site testing script for webscope.

Runs scans on a list of real websites, collects results,
analyzes false positives, and generates a report.
"""

import asyncio
import json
import sys
import time
from pathlib import Path
from dataclasses import dataclass, asdict
from typing import List, Dict, Any, Optional
from datetime import datetime

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from webscope.scanner import scan_site, ScanError, ScanResult, Finding
from webscope.scoring import is_false_positive


# Heuristic FP detection rules
FP_HEURISTICS = {
    # Rules that are often false positives
    "links/target-blank-noopener": True,  # Often intentional for external links
    "content/empty-link-name": True,      # Often icon-only links, social icons
    "viewport/target-size": True,         # Often acceptable design choice
    "console/warning": True,              # Usually non-actionable
    "console/info": True,                 # Usually non-actionable
    "blink": True,                        # Deprecated but sometimes intentional
    "marquee": True,                      # Deprecated but sometimes intentional
}

# Rules that are NEVER FP (real issues)
NEVER_FP = {
    "content/image-alt",
    "color-contrast",
    "content/duplicate-id",
    "aria-required-children",
    "aria-required-parent",
    "aria-allowed-attr",
    "aria-valid-attr-value",
    "form/label",
    "forms/control-without-label",
    "link-name",
    "image-alt",
    "list",
    "listitem",
    "heading-order",
    "content/heading-order",
    "region",
    "landmark-unique",
    "page-has-heading-one",
    "content/missing-h1",
    "content/no-h1",
}

def is_likely_fp(finding) -> bool:
    """Heuristic: is this finding likely a false positive?"""
    rule = finding.rule
    
    # Never FP rules
    if rule in NEVER_FP:
        return False
    
    # Known FP rules
    if rule in FP_HEURISTICS:
        return True
    
    # Heuristic: console errors from third-party domains
    if rule in ("console/error", "console/failed-request"):
        if finding.source:
            return True
    
    return False


@dataclass
class SiteTestResult:
    url: str
    success: bool
    score: Optional[int] = None
    findings_count: int = 0              # raw findings (including FPs)
    clean_findings_count: int = 0        # findings after FP filtering
    user_fp_count: int = 0               # user-marked FPs
    heuristic_fp_count: int = 0          # heuristic-detected FPs
    findings_by_severity: Dict[str, int] = None
    findings_by_rule: Dict[str, int] = None
    clean_findings_by_severity: Dict[str, int] = None
    clean_findings_by_rule: Dict[str, int] = None
    duration_ms: int = 0
    pages_scanned: int = 0
    error: Optional[str] = None
    top_findings: List[Dict] = None
    clean_top_findings: List[Dict] = None
    
    def __post_init__(self):
        if self.findings_by_severity is None:
            self.findings_by_severity = {}
        if self.findings_by_rule is None:
            self.findings_by_rule = {}
        if self.clean_findings_by_severity is None:
            self.clean_findings_by_severity = {}
        if self.clean_findings_by_rule is None:
            self.clean_findings_by_rule = {}
        if self.top_findings is None:
            self.top_findings = []
        if self.clean_top_findings is None:
            self.clean_top_findings = []


async def scan_site_async(url: str, timeout_ms: int = 60000) -> SiteTestResult:
    """Scan a single site and return structured result with FP analysis."""
    start_time = time.time()
    
    try:
        # Run sync scan_site in thread pool
        loop = asyncio.get_event_loop()
        result, crawl_result = await loop.run_in_executor(
            None,
            lambda: scan_site(
                url,
                max_pages=10,
                max_depth=2,
                timeout_ms=timeout_ms,
                allow_private=False,
                headless=True,
            )
        )
        
        # ===== RAW METRICS (all findings) =====
        raw_findings = result.findings
        raw_severity_counts = {}
        raw_rule_counts = {}
        for f in raw_findings:
            sev = f.severity.value
            raw_severity_counts[sev] = raw_severity_counts.get(sev, 0) + 1
            raw_rule_counts[f.rule] = raw_rule_counts.get(f.rule, 0) + 1
        
        # ===== FP DETECTION =====
        user_fp = [f for f in raw_findings if f.details.get("fp", False)]
        heuristic_fp = [f for f in raw_findings if is_likely_fp(f) and not f.details.get("fp", False)]
        
        # ===== CLEAN FINDINGS (exclude both user and heuristic FPs) =====
        clean_findings = [f for f in raw_findings 
                         if not f.details.get("fp", False) and not is_likely_fp(f)]
        
        # Count by severity (clean)
        clean_severity_counts = {}
        clean_rule_counts = {}
        for f in clean_findings:
            sev = f.severity.value
            clean_severity_counts[sev] = clean_severity_counts.get(sev, 0) + 1
            clean_rule_counts[f.rule] = clean_rule_counts.get(f.rule, 0) + 1
        
        # Top findings raw
        sorted_raw = sorted(raw_findings, key=lambda x: (x.severity.rank, -len(x.selector or "")))
        top_findings = [
            {"rule": f.rule, "severity": f.severity.value, "title": f.title,
             "url": f.url, "selector": f.selector}
            for f in sorted_raw[:10]
        ]
        
        # Top findings clean
        sorted_clean = sorted(clean_findings, key=lambda x: (x.severity.rank, -len(x.selector or "")))
        clean_top_findings = [
            {"rule": f.rule, "severity": f.severity.value, "title": f.title,
             "url": f.url, "selector": f.selector}
            for f in sorted_clean[:10]
        ]
        
        duration_ms = int((time.time() - start_time) * 1000)
        
        return SiteTestResult(
            url=url,
            success=True,
            score=result.score,
            findings_count=len(raw_findings),
            clean_findings_count=len(clean_findings),
            user_fp_count=len(user_fp),
            heuristic_fp_count=len(heuristic_fp),
            findings_by_severity=raw_severity_counts,
            findings_by_rule=raw_rule_counts,
            clean_findings_by_severity=clean_severity_counts,
            clean_findings_by_rule=clean_rule_counts,
            duration_ms=duration_ms,
            pages_scanned=result.pages_scanned,
            top_findings=top_findings,
            clean_top_findings=clean_top_findings,
        )
        
    except Exception as e:
        duration_ms = int((time.time() - start_time) * 1000)
        return SiteTestResult(
            url=url,
            success=False,
            error=f"{type(e).__name__}: {e}",
            duration_ms=duration_ms,
        )


async def run_real_site_tests(urls: List[str], output_dir: Path) -> Dict[str, Any]:
    """Run tests on multiple sites and generate report."""
    output_dir.mkdir(parents=True, exist_ok=True)
    
    print(f"Testing {len(urls)} sites...")
    print("=" * 60)
    
    results = []
    for i, url in enumerate(urls, 1):
        print(f"\n[{i}/{len(urls)}] Scanning: {url}")
        result = await scan_site_async(url)
        results.append(result)
        
        if result.success:
            print(f"  ✓ Score: {result.score} | Findings: {result.findings_count} | Time: {result.duration_ms}ms")
            for sev, count in sorted(result.findings_by_severity.items()):
                print(f"    {sev}: {count}")
        else:
            print(f"  ✗ Error: {result.error}")
    
    # Generate summary
    successful = [r for r in results if r.success]
    failed = [r for r in results if not r.success]
    
    # Aggregate metrics
    total_findings = sum(r.findings_count for r in successful)
    total_clean_findings = sum(r.clean_findings_count for r in successful)
    total_user_fp = sum(r.user_fp_count for r in successful)
    total_heuristic_fp = sum(r.heuristic_fp_count for r in successful)
    
    severity_totals = {}
    rule_totals = {}
    clean_severity_totals = {}
    clean_rule_totals = {}
    score_sum = 0
    
    for r in successful:
        score_sum += r.score or 0
        for sev, count in r.findings_by_severity.items():
            severity_totals[sev] = severity_totals.get(sev, 0) + count
        for rule, count in r.findings_by_rule.items():
            rule_totals[rule] = rule_totals.get(rule, 0) + count
        for sev, count in r.clean_findings_by_severity.items():
            clean_severity_totals[sev] = clean_severity_totals.get(sev, 0) + count
        for rule, count in r.clean_findings_by_rule.items():
            clean_rule_totals[rule] = clean_rule_totals.get(rule, 0) + count
    
    avg_score = score_sum / len(successful) if successful else 0
    
    # Top problematic rules (raw and clean)
    top_rules = sorted(rule_totals.items(), key=lambda x: -x[1])[:15]
    clean_top_rules = sorted(clean_rule_totals.items(), key=lambda x: -x[1])[:15]
    
    # Score distribution
    score_dist = {"0-20": 0, "21-40": 0, "41-60": 0, "61-80": 0, "81-100": 0}
    for r in successful:
        s = r.score or 0
        if s <= 20: score_dist["0-20"] += 1
        elif s <= 40: score_dist["21-40"] += 1
        elif s <= 60: score_dist["41-60"] += 1
        elif s <= 80: score_dist["61-80"] += 1
        else: score_dist["81-100"] += 1
    
    # Generate report
    report = {
        "timestamp": datetime.now().isoformat(),
        "total_sites": len(urls),
        "successful": len(successful),
        "failed": len(failed),
        "success_rate": len(successful) / len(urls) if urls else 0,
        "avg_score": round(avg_score, 1),
        "total_findings": total_findings,
        "total_clean_findings": total_clean_findings,
        "total_user_fp": total_user_fp,
        "total_heuristic_fp": total_heuristic_fp,
        "avg_findings_per_site": round(total_findings / len(successful), 1) if successful else 0,
        "avg_clean_findings_per_site": round(total_clean_findings / len(successful), 1) if successful else 0,
        "severity_distribution": severity_totals,
        "clean_severity_distribution": clean_severity_totals,
        "top_rules": top_rules,
        "clean_top_rules": clean_top_rules,
        "score_distribution": score_dist,
        "failed_sites": [{"url": r.url, "error": r.error} for r in failed],
        "detailed_results": [asdict(r) for r in results],
    }
    
    # Save JSON report
    json_path = output_dir / f"real_site_test_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    
    # Generate markdown report
    md_path = output_dir / f"real_site_test_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
    with open(md_path, 'w', encoding='utf-8') as f:
        f.write(f"# Real Site Test Report\n\n")
        f.write(f"**Date:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"**Total sites tested:** {len(urls)}\n")
        f.write(f"**Successful:** {len(successful)} | **Failed:** {len(failed)}\n")
        f.write(f"**Success rate:** {report['success_rate']*100:.1f}%\n")
        f.write(f"**Average score:** {avg_score:.1f}\n")
        f.write(f"**Total findings (raw):** {total_findings}\n")
        f.write(f"**Total findings (clean):** {total_clean_findings}\n")
        f.write(f"**User-marked FP:** {total_user_fp}\n")
        f.write(f"**Heuristic FP:** {total_heuristic_fp}\n")
        f.write(f"**FP reduction:** {((total_findings - total_clean_findings) / total_findings * 100):.1f}%\n")
        f.write(f"**Avg findings per site (raw):** {report['avg_findings_per_site']:.1f}\n")
        f.write(f"**Avg findings per site (clean):** {report['avg_clean_findings_per_site']:.1f}\n\n")
        
        f.write("## Severity Distribution (Raw)\n\n")
        for sev in ["critical", "serious", "moderate", "minor"]:
            if sev in severity_totals:
                f.write(f"- **{sev.capitalize()}:** {severity_totals[sev]}\n")
        
        f.write("\n## Severity Distribution (Clean)\n\n")
        for sev in ["critical", "serious", "moderate", "minor"]:
            if sev in clean_severity_totals:
                f.write(f"- **{sev.capitalize()}:** {clean_severity_totals[sev]}\n")
        
        f.write("\n## Score Distribution\n\n")
        for range_name, count in score_dist.items():
            f.write(f"- {range_name}: {count} sites\n")
        
        f.write("\n## Top Problematic Rules (Raw)\n\n")
        for rule, count in top_rules:
            f.write(f"- **{rule}**: {count} occurrences\n")
        
        f.write("\n## Top Problematic Rules (Clean)\n\n")
        for rule, count in clean_top_rules:
            f.write(f"- **{rule}**: {count} occurrences\n")
        
        f.write("\n## Failed Sites\n\n")
        for failed_site in report["failed_sites"]:
            f.write(f"- **{failed_site['url']}**: {failed_site['error']}\n")
        
        f.write("\n## Detailed Results\n\n")
        for r in results:
            if r.success:
                f.write(f"### ✓ {r.url}\n")
                f.write(f"- **Score:** {r.score}/100\n")
                f.write(f"- **Findings (raw):** {r.findings_count}\n")
                f.write(f"- **Findings (clean):** {r.clean_findings_count}\n")
                f.write(f"- **User FP:** {r.user_fp_count}\n")
                f.write(f"- **Heuristic FP:** {r.heuristic_fp_count}\n")
                f.write(f"- **Time:** {r.duration_ms}ms\n")
                f.write(f"- **Pages scanned:** {r.pages_scanned}\n")
                if r.top_findings:
                    f.write("- **Top findings (raw):**\n")
                    for tf in r.top_findings[:3]:
                        f.write(f"  - [{tf['severity'].upper()}] {tf['rule']}: {tf['title']}\n")
                if r.clean_top_findings:
                    f.write("- **Top findings (clean):**\n")
                    for tf in r.clean_top_findings[:3]:
                        f.write(f"  - [{tf['severity'].upper()}] {tf['rule']}: {tf['title']}\n")
            else:
                f.write(f"### ✗ {r.url}\n")
                f.write(f"- **Error:** {r.error}\n")
            f.write("\n")
    
    print(f"\n{'='*60}")
    print(f"SUMMARY")
    print(f"{'='*60}")
    print(f"Total sites: {len(urls)}")
    print(f"Successful: {len(successful)} ({report['success_rate']*100:.1f}%)")
    print(f"Failed: {len(failed)}")
    print(f"Average score: {avg_score:.1f}")
    print(f"Total findings (raw): {total_findings}")
    print(f"Total findings (clean): {total_clean_findings}")
    print(f"User-marked FP: {total_user_fp}")
    print(f"Heuristic FP: {total_heuristic_fp}")
    print(f"FP reduction: {((total_findings - total_clean_findings) / total_findings * 100):.1f}%")
    print(f"Avg findings per site (raw): {report['avg_findings_per_site']:.1f}")
    print(f"Avg findings per site (clean): {report['avg_clean_findings_per_site']:.1f}")
    print(f"\nReports saved to:")
    print(f"  JSON: {json_path}")
    print(f"  Markdown: {md_path}")
    
    return report


def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="Run webscope scans on real websites")
    parser.add_argument("urls", nargs="+", help="URLs to scan")
    parser.add_argument("-o", "--output", default="test_results", help="Output directory")
    parser.add_argument("--timeout", type=int, default=60000, help="Timeout per site (ms)")
    
    args = parser.parse_args()
    
    output_dir = Path(args.output)
    
    # Run tests
    asyncio.run(run_real_site_tests(args.urls, output_dir))


if __name__ == "__main__":
    main()
