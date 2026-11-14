"""`python -m hermes.synthetic [--out DIR] [--seed N]` writes the synthetic world."""

import argparse

from hermes.synthetic.generate import generate

p = argparse.ArgumentParser(prog="hermes.synthetic")
p.add_argument("--out", default="storage/synthetic")
p.add_argument("--seed", type=int, default=42)
a = p.parse_args()
m = generate(a.out, a.seed)
print(f"wrote {len(m['files'])} files to {a.out} (seed {a.seed})")
