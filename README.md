# SteLLaFuzz

SteLLaFuzz is a structure-guided fuzzing framework that leverages large language models (LLMs) to generate protocol-aware seed inputs for testing network protocol implementations. Unlike conventional fuzzers that rely on random mutations or fixed dictionaries, SteLLaFuzz extracts message types, structural formats, and valid sequences from raw seed messages, enabling it to generate semantically valid and structurally diverse inputs.

The framework is built on top of [ProFuzzBench](https://github.com/profuzzbench/profuzzbench) and ships three fuzzers — `aflnet`, `chatafl`, and `stellafuzz` — so they can be compared on the same subjects under identical conditions.

---

## Prerequisites

- Linux host with **Docker** installed and a running Docker daemon (the scripts use `sudo` for `apt-get` and assume your user can run `docker`).
- An **OpenAI API key** (used by `chatafl` and `stellafuzz` for LLM-assisted generation).
- Python 3 with `pandas` and `matplotlib` (installed by `deps.sh`).
- Disk space for Docker images: building the full benchmark (14 subjects × 3 fuzzers) takes roughly an hour and tens of GB.

---

## Quick Start

| Step | Command | Notes |
| --- | --- | --- |
| **1 · Install dependencies** | `./deps.sh` | Installs `docker`, `python3`, `python3-pip`, then `pip3 install matplotlib pandas`. Prompts for `sudo`. |
| **2 · Build images** | `KEY=<OPENAI_API_KEY> ./setup.sh` | Injects the API key into the subjects' Dockerfiles and `ChatAFL/chat-llm.h`, copies the fuzzers into each subject, and builds all Docker images. |
| **3 · Run fuzzing** | `./run.sh <N_CONTAINERS> <MINUTES> <SUBJECTS> <FUZZERS>` | e.g. `./run.sh 1 300 pure-ftpd stellafuzz`. Comma-separate multiple subjects/fuzzers. |
| **4 · Analyze results** | `./analyze.sh <SUBJECTS> [MINUTES]` | Generates coverage/state PNGs and copies them with the raw results into `benchmark/res_<subject>_<timestamp>/`. |
| **5 · Clean up** | `./clean.sh` | Stops and removes containers and images for all subjects. |

`<MINUTES>` defaults to `1440` (24 h) if omitted in `analyze.sh`.

---

## Repository Layout

```
SteLLaFuzz
├── aflnet/         AFLNet, modified to emit states and state transitions
├── ChatAFL/        ChatAFL source
├── SteLLaFuzz/     SteLLaFuzz source (an AFL/AFLNet derivative)
│   └── SteLLaFuzz/
│       ├── LLM/        LLM-driven extraction & sequence generation
│       ├── utility/    tunable constants (utility.py)
│       └── ...
├── benchmark/      modified ProFuzzBench (subjects, build/exec/analysis scripts)
├── experiment-data/  results from the paper's runs
├── deps.sh         install dependencies (uses sudo)
├── setup.sh        inject API key, copy fuzzers, build Docker images
├── run.sh          run fuzzers on subjects and collect data
├── analyze.sh      generate coverage/state graphs from results
├── clean.sh        remove containers and images
├── LICENSE         Apache 2.0
└── README.md       this file
```

`setup.sh` copies `aflnet/`, `ChatAFL/`, and `SteLLaFuzz/` into every subject under `benchmark/subjects/<PROTOCOL>/<SUBJECT>/` (as `aflnet/`, `chatafl/`, and `stellafuzz/`) before building. These copies are git-ignored.

---

## Supported Subjects & Fuzzers

**Subjects** (14): `bftpd`, `dcmtk`, `dnsmasq`, `exim`, `forked-daapd`, `kamailio`, `lightftp`, `lighttpd1`, `live555`, `openssh`, `openssl`, `proftpd`, `pure-ftpd`, `tinydtls`.

These span the FTP, DICOM, DNS, SMTP, DAAP, SIP, RTSP, SSH, TLS, DTLS, and HTTP protocols.

**Fuzzers** (3): `aflnet`, `chatafl`, `stellafuzz`.

Pass `all` to either list to select every subject or fuzzer.

---

## Running Experiments

`run.sh` schedules `N_CONTAINERS` Docker containers; each container isolates one fuzzer/subject pair to avoid cross-interference. Results for each subject are collected as compressed archives under `benchmark/results-<subject>/`.

```bash
./run.sh <N_CONTAINERS> <MINUTES> <SUBJECTS> <FUZZERS>
```

| Argument | Meaning |
| --- | --- |
| `N_CONTAINERS` | Number of parallel containers (runs per fuzzer/subject pair) |
| `MINUTES` | Fuzzing duration per run (converted to seconds internally) |
| `SUBJECTS` | Comma-separated subject list, or `all` |
| `FUZZERS` | Comma-separated fuzzer list, or `all` |

Optional environment variables (defaults in parentheses):

| Variable | Meaning | Default |
| --- | --- | --- |
| `SKIPCOUNT` | Snapshot interval for coverage/state sampling | `1` |
| `TEST_TIMEOUT` | Per-test-case timeout in ms passed to the fuzzer | `5000` |

The configuration used in the SteLLaFuzz paper:

```bash
./run.sh 10 1440 \
  dcmtk,dnsmasq,tinydtls,openssh,openssl,forked-daapd,bftpd,lightftp,proftpd,pure-ftpd,live555,exim,kamailio \
  aflnet,chatafl,stellafuzz
```

While containers are running, `docker ps -a | grep <subject>` shows their status (`Up …` while fuzzing, `Exited …` once complete). Run `analyze.sh` after they exit.

---

## Tuning Options

LLM behavior is controlled by constants in
[`SteLLaFuzz/SteLLaFuzz/utility/utility.py`](SteLLaFuzz/SteLLaFuzz/utility/utility.py):

| Variable | Meaning | Default |
| --- | --- | --- |
| `MODEL` | OpenAI model id used for LLM calls | `gpt-4o-mini` |
| `SEQUENCE_REPEAT` | Number of alternative dialogues generated per seed | `1` |
| `LLM_RETRY` | Retry attempts before giving up on a prompt | `3` |

Edit these and re-run `setup.sh` to rebuild the affected images.

---

## License

Released under the **Apache 2.0** license. See [LICENSE](LICENSE).

---

## Acknowledgements

- [AFLNet](https://github.com/aflnet/aflnet) — state-feedback greybox fuzzing engine.
- [ChatAFL](https://github.com/ChatAFLndss/ChatAFL) — LLM-guided protocol fuzzing.
- [ProFuzzBench](https://github.com/profuzzbench/profuzzbench) — reproducible stateful-protocol fuzzing benchmark.
