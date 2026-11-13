"""Compare the original and extended samples using saved run-level results only.

Run after make_report.py has refreshed reports/live/runs.csv. No API access.
Incomplete input is rejected so partial samples cannot masquerade as the final
five-repeat extension. The original and full samples overlap; comparisons are
strictly descriptive, without post hoc significance tests.
"""
import argparse
from pathlib import Path
import sys

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from ie498.analysis import bootstrap, plt, wilson


H_VALUES = (0, 1, 5, 20, 100)
MODES = ('clear', 'full', 'compressed')


def boolean_column(frame, name):
    values = frame[name]
    if values.dtype == bool:
        return values
    parsed = values.astype(str).str.lower().map({'true': True, 'false': False})
    if parsed.isna().any():
        raise ValueError(f'{name} contains missing or invalid booleans')
    return parsed.astype(bool)


def load_complete_sample(path):
    runs = pd.read_csv(path)
    required = {'id', 'stage', 'architecture', 'provider', 'status', 'H', 'mode',
                'repetition', 'T', 'rounds_completed', 'CI', 'effective_success',
                'price_success', 'profit_success', 'eligible_primary', 'eligible_reference'}
    missing = required - set(runs.columns)
    if missing:
        raise ValueError(f'Refresh run analysis first; missing columns: {sorted(missing)}')
    bullet = runs[(runs.stage == 'formation') & (runs.architecture == 'bullet_memory') &
                  (runs.provider == 'openai')].copy()
    reference = runs[(runs.stage == 'formation_reference') &
                     (runs.architecture == 'paper_reference') & (runs.provider == 'openai')].copy()
    expected = {(mode, h, rep) for mode in MODES for h in H_VALUES for rep in range(1, 6)}
    keys = list(zip(bullet['mode'], bullet.H, bullet.repetition))
    if len(keys) != 75 or len(set(keys)) != 75 or set(keys) != expected:
        raise ValueError('Expected exactly 75 distinct planned bullet runs: all 15 cells × repeats 1–5')
    if len(reference) != 5 or set(reference.repetition) != set(range(1, 6)):
        raise ValueError('Expected exactly five new formal paper-reference repeats 1–5')
    if not ((reference.H == 100) & (reference['mode'] == 'full')).all():
        raise ValueError('Formal paper-reference runs must use H=100 and mode=full')
    for name, frame, eligibility in [('bullet', bullet, 'eligible_primary'),
                                      ('reference', reference, 'eligible_reference')]:
        if not ((frame.status == 'completed') & (frame['T'] == 300) &
                (frame.rounds_completed == 300) & boolean_column(frame, eligibility)).all():
            raise ValueError(f'The {name} sample is incomplete; final comparison withheld')
        if frame.id.duplicated().any() or not np.isfinite(frame.CI).all():
            raise ValueError(f'Invalid {name} identifiers or CI values')
        for col in ('effective_success', 'price_success', 'profit_success'):
            frame[col] = boolean_column(frame, col)
    return bullet, reference


def summarize(group, cohort):
    n = len(group)
    k = int(group.effective_success.sum())
    low, high = wilson(k, n)
    ci_low, ci_high = bootstrap(group.CI)
    return dict(cohort=cohort, n=n, successes=k, success_rate=k/n,
                wilson_low=low, wilson_high=high, wilson_width=high-low,
                mean_CI=float(group.CI.mean()), sd_CI=float(group.CI.std(ddof=1)),
                min_CI=float(group.CI.min()), max_CI=float(group.CI.max()),
                CI_bootstrap_low=ci_low, CI_bootstrap_high=ci_high)


def compare(bullet):
    rows = []
    for mode in MODES:
        for h in H_VALUES:
            group = bullet[(bullet['mode'] == mode) & (bullet.H == h)]
            for cohort, part in [('original_r1_3', group[group.repetition <= 3]),
                                 ('added_r4_5', group[group.repetition >= 4]),
                                 ('extended_r1_5', group)]:
                rows.append(dict(mode=mode, H=h, **summarize(part, cohort)))
    return pd.DataFrame(rows)


def plot_reference(bullet, reference, destination):
    fig, ax = plt.subplots(figsize=(9, 5))
    labels = ['clear', 'full', 'compressed', 'PLANS/INSIGHTS']
    for index, frame in enumerate([bullet[(bullet.H == 100) & (bullet['mode'] == mode)]
                                  for mode in MODES] + [reference]):
        frame = frame.sort_values('repetition')
        positions = index + np.linspace(-.12, .12, len(frame))
        ax.scatter(positions, frame.CI, label=labels[index], s=44, zorder=3)
        ax.plot([index-.2, index+.2], [frame.CI.mean()]*2, color='black', lw=2)
        for x, row in zip(positions, frame.itertuples()):
            ax.annotate(f'r{int(row.repetition)}', (x, row.CI), xytext=(3, 5),
                        textcoords='offset points', fontsize=7)
    ax.axhline(0, color='gray', ls='--', label='Nash CI=0')
    ax.axhline(1, color='firebrick', ls=':', label='Joint optimum CI=1')
    ax.set_xticks(range(4), labels)
    ax.set(ylabel='Run-level CI (final 50 rounds)', xlabel='Memory condition, H=100',
           title='Five independent runs per condition; black bars show means')
    ax.legend(fontsize=8, ncol=3)
    fig.tight_layout()
    fig.savefig(destination, dpi=160)
    plt.close(fig)


def plot_precision(precision, destination):
    fig, ax = plt.subplots(figsize=(10, 8))
    cells = [(mode, h) for mode in MODES for h in H_VALUES]
    for cohort, offset, color, label in [('original_r1_3', -.12, 'tab:blue', 'Original n=3'),
                                        ('extended_r1_5', .12, 'tab:orange', 'Extended n=5')]:
        group = precision[precision.cohort == cohort].set_index(['mode', 'H']).loc[cells]
        values = group.success_rate.to_numpy()
        errors = np.stack([np.maximum(0, values-group.wilson_low.to_numpy()),
                           np.maximum(0, group.wilson_high.to_numpy()-values)])
        ax.errorbar(values, np.arange(len(cells))+offset, xerr=errors,
                    fmt='o', capsize=3, color=color, label=label)
    ax.axvline(.8, color='gray', ls=':', label='80% sample criterion')
    ax.set_yticks(range(len(cells)), [f'{mode}, H={h}' for mode, h in cells])
    ax.invert_yaxis()
    ax.set(xlim=(-.03, 1.03), xlabel='Effective success fraction with Wilson 95% interval',
           title='Original and extended samples overlap; intervals are descriptive')
    ax.legend(fontsize=8, loc='lower right')
    fig.tight_layout()
    fig.savefig(destination, dpi=160)
    plt.close(fig)


def interpretation(bullet, reference, precision):
    original = bullet[bullet.repetition <= 3]
    added = bullet[bullet.repetition >= 4]
    old = precision[precision.cohort == 'original_r1_3'].set_index(['mode', 'H'])
    full = precision[precision.cohort == 'extended_r1_5'].set_index(['mode', 'H'])
    widths = full.wilson_width-old.wilson_width
    changes = full.mean_CI-old.mean_CI
    qualifying = full[full.success_rate >= .8]
    reference_stats = summarize(reference, 'reference_r1_5')
    lines = [
        '## Five-repeat extension: descriptive findings', '',
        f'The expanded bullet-memory matrix contains {len(bullet)} complete 300-round runs '
        f'across 15 conditions. The original {len(original)} runs have '
        f'{int(original.effective_success.sum())} effective successes; the {len(added)} added '
        f'runs have {int(added.effective_success.sum())}. The full matrix has '
        f'{int(bullet.effective_success.sum())}/{len(bullet)} effective successes and '
        f'{int(bullet.price_success.sum())}/{len(bullet)} price-criterion successes. '
        'These pooled counts describe coverage; each condition remains the unit of comparison.', '',
        f'Across the 15 cells, mean CI ranges from {full.mean_CI.min():.3f} to '
        f'{full.mean_CI.max():.3f}; within-cell sample standard deviations range from '
        f'{full.sd_CI.min():.3f} to {full.sd_CI.max():.3f}. Extending the sample changes '
        f'cell mean CI by {changes.min():+.3f} to {changes.max():+.3f}. '
        f'Wilson interval widths range from {old.wilson_width.min():.3f}–'
        f'{old.wilson_width.max():.3f} at n=3 and {full.wilson_width.min():.3f}–'
        f'{full.wilson_width.max():.3f} at n=5; widths decrease in '
        f'{int((widths < -1e-12).sum())}/15 cells. Interval widths depend on the observed '
        'success count as well as sample size, so an increase in repeats need not narrow every realized interval.', '',
        f'{len(qualifying)} of 15 cells meet the predefined 80% sample effective-success '
        'criterion, which requires at least 4/5 successful runs at n=5. The minimum tested '
        'effective H is reported separately for each bullet-memory mode in '
        '`live/minimum_tested_effective_H.json`; it is not a population threshold.', '',
        f'The separately added H100 paper-reference condition contains {len(reference)} new '
        f'complete runs, with {reference_stats["successes"]}/{len(reference)} effective successes '
        f'(Wilson 95% interval [{reference_stats["wilson_low"]:.3f}, '
        f'{reference_stats["wilson_high"]:.3f}]). Its mean CI is '
        f'{reference_stats["mean_CI"]:.3f}, sample standard deviation '
        f'{reference_stats["sd_CI"]:.3f}, and run-level range '
        f'[{reference_stats["min_CI"]:.3f}, {reference_stats["max_CI"]:.3f}]. '
        'These observations are not pooled with full bullet memory or historical pilots.', '',
        'The extension and new architectural condition were requested after inspecting the '
        'original results. Five repeats remain a small sample. Repeats 4–5 are a separate '
        'descriptive cohort, not a randomized time contrast; original and extended estimates '
        'overlap and must not be treated as independent samples. New paper-reference labels '
        '1–3 denote additional independent runs, not historical execution alongside the '
        'original repeats or matched random seeds. Execution-time/model-service differences '
        'and post-result design changes limit causal and confirmatory interpretations. '
        'No post hoc significance test is used to decide whether to stop or favor a condition.', '',
        '![H100 reference comparison](live/reference_comparison.png)', '',
        '![Success-rate interval comparison](live/extension_precision.png)', '',
        'See `live/extension_precision.csv` for every condition and cohort, including '
        'success fractions, Wilson intervals, CI means, sample standard deviations, ranges, '
        'and descriptive bootstrap intervals. The two-run added cohort is particularly imprecise.', '',
    ]
    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reports', type=Path, default=ROOT/'reports')
    args = parser.parse_args()
    live = args.reports/'live'
    bullet, reference = load_complete_sample(live/'runs.csv')
    precision = compare(bullet)
    precision.to_csv(live/'extension_precision.csv', index=False)
    plot_reference(bullet, reference, live/'reference_comparison.png')
    plot_precision(precision, live/'extension_precision.png')
    path = args.reports/'extension_interpretation.md'
    path.write_text(interpretation(bullet, reference, precision))
    print(path)


if __name__ == '__main__':
    main()
