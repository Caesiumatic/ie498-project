# Original-paper source search receipt

Checked on 2026-11-14 UTC (2026-11-13 in America/Chicago).

Target: Sara Fish, Yannai A. Gonczarowski, and Ran I. Shorrer, *Algorithmic Collusion by Large Language Models*, arXiv:2404.00806. This receipt records a read-only source search, not experimental results or a claim that the authors' original software has been recovered.

## Official sources checked

| Source | Exact URL | Finding |
| --- | --- | --- |
| Sara Fish's research page | <https://sarafish.com/> | The collusion-paper entry links to arXiv but does not expose a code/data link. Other papers on the same page explicitly have Code links. |
| Yannai Gonczarowski's publications | <https://yannai.gonch.name/scientific/research.html> | The collusion-paper entry links to arXiv. The nearby GitHub link belongs to EconEvals, not this paper. |
| Ran Shorrer's research page | <https://rshorrer.weebly.com/research.html> | The collusion-paper entry links to arXiv, without a code/data link. |
| Current pinned paper | <https://arxiv.org/abs/2404.00806v6> | Version 6 was submitted on 2026-08-31. The existing local PDF/text and hashes remain recorded in `sources/manifest.json`. |
| Current pinned PDF | <https://arxiv.org/pdf/2404.00806v6> | Searched the local text and inspected every embedded URI. No code repository or original-data download was identified. |
| First paper version | <https://arxiv.org/abs/2404.00806v1> and <https://arxiv.org/pdf/2404.00806v1> | Submitted on 2024-03-31; downloaded and compared relevant design statements with v6. |
| Author's general LLM tool | <https://github.com/sara-fish/gpt_cli/blob/master/README.md> | A general command-line chat interface, not an identified replication package for the collusion paper. |

GitHub repository searches included the exact paper title, `user:sara-fish collusion`, `user:sara-fish pricing`, `user:sara-fish`, and the author names. The author-account query returned ten public repositories accessible through the connector, none identified as the collusion paper's code. Public web searches combined the title, author names, and arXiv identifier with `code`, `data`, `github`, and `replication package`.

**Result:** no author-published code repository or original-data package was identified in these checks. This is a bounded search result, not proof that no such materials exist or could become available. No author was contacted. No official implementation commit can therefore be pinned from this search.

## Third-party repositories distinguished from official code

| Checked repository | Identity and relevant limitations |
| --- | --- |
| <https://github.com/fvwaldow/algorithmic-collusion-LLM/blob/master/README.md> | Its README describes an extension of Fish et al. using locally hosted Ollama models, including asymmetric firms. It is not presented as the original authors' implementation. |
| <https://github.com/luciasauer/algorithmic_pricing_llms/blob/main/README.md> | A Barcelona School of Economics master's thesis by Julian Romero, Lucia Sauer, and Moritz Peist. It uses Mistral models and extends duopoly to larger oligopolies. It is not the original authors' repository. |
| <https://github.com/ShangjieShi/Spring-Research/blob/main/README.md> | The README identifies a replication of Fish et al.; no original-author affiliation or official-code provenance was established. |

These repositories were inspected for provenance, not adopted as authoritative implementations of the paper. Their code and data were not used to fill unspecified details silently.

## Version and sample-size checks

- In the pinned v6 text, Figure 2's notes at lines 583–584 specify **seven runs for each currency scale alpha in {1, 3.2, 10} and each prefix P1/P2**. Section 3's 21 runs are consequently 21 per prefix, not 21 per scale. The v1 Figure 3 notes give the same allocation. Reducing to one run per scale would retain three runs per prefix; reducing to one total run per prefix cannot retain coverage of all three scales. A new replication must explicitly state its allocation.
- V1 footnote 14 describes the textual price ceiling as gamma times the joint-monopoly price, with gamma drawn from Uniform[1.5, 2.5]. V6 footnote 18, local lines 438–441, supplies the realized value 2.34 and states that it was drawn from that distribution. This wording difference does **not** establish that v1 independently redrew gamma for every run. The fixed v6 description should not be replaced with fresh random draws on that inference.
- The central P1/P2 instructions in v1 and v6 agree in substance. V1 Appendix B also records GPT-4-0613, temperature 1, template parsing with numeric extraction, and stopping after ten consecutive malformed outputs. The original code's exact parser and formatting details remain unavailable from this search.

The downloaded v1 PDF was 1,558,415 bytes with SHA-256 `e0af95ba6fed1bc96de72c472e202f54f91b22140adb63c232e9c302e4b74559`. It and its text extraction were used only as temporary comparison files; v6 remains the repository's pinned source. This receipt does not replace the experiment protocol or authorize treating unspecified implementation choices as exact reproduction of the authors' software.
