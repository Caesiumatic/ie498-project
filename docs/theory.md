# Economic benchmarks and memory mechanisms

Let `s_i=q_i/beta` denote product i's market share and `s_0` the outside-option share. Logit demand satisfies:

\[
\frac{\partial q_i}{\partial p_i}=-\frac{q_i(1-s_i)}{\alpha\mu},\qquad
\frac{\partial q_j}{\partial p_i}=\frac{q_j s_i}{\alpha\mu}\quad(j\ne i).
\]

A firm's individual first-order condition is

\[
1-\frac{p_i-\alpha c_i}{\alpha\mu}(1-s_i)=0.
\]

The code jointly solves both first-order conditions, then independently solves each firm's one-dimensional best response to verify that Nash prices are mutual best responses. The joint optimum maximizes the sum of both profits; under symmetry, its first-order condition simplifies to `p−alpha*c=alpha*mu/s_0`. This is the joint optimum for two differentiated products under common control, not a single-product monopoly.

Researchers use these formulas only for settlement and analysis. Agents do not know demand or the Nash/joint-optimal prices; they must explore through permitted feedback and their own textual strategies.

The researcher observes 300 rounds, but sellers are not told the remaining horizon. No explicit discount factor is supplied, and the study does not solve all repeated-game equilibria. Static Nash and the joint optimum are numerical benchmarks; high prices and profits alone do not establish a particular repeated-game equilibrium.

Memory design changes agents' visible state:

- H=0/clear provides fixed inputs with fresh sampling, serving as a static model-prior control.
- H=0/full or compressed can accumulate self-generated plans but receives no market feedback; those plans are not new market observations.
- H≥1 supplies real feedback. Full archives may retain observations or judgments older than H, so raw history length and overall memory capacity are different concepts.
- Compressed shortens only the seller's decision context. The external archive and compressor still use the full sequence; their resource costs are measured separately.

The two firms, rounds within a run, and same-source states across branches are correlated. The independent formation unit is a complete run; for maintenance and shock, the source unit is the parent. One successful run can describe a formation path but cannot estimate success probability precisely. One failed run likewise cannot establish that a memory mechanism is universally ineffective.
