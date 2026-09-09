#!/bin/bash
set -euxo pipefail

REPOS="nionutils niondata nionui nionswift-io nionswift nionswift-instrumentation-kit nionswift-usim"

DEPS="numpy scipy tzlocal h5py imageio pillow pytz tifffile types-pytz types-tzlocal"

cd /workspaces
for r in $REPOS; do
  # nionswift is already checked out here by Codespaces; the rest get cloned
  [ -d "$r/.git" ] || git clone --filter=blob:none "https://github.com/nion-software/$r.git" "$r"
done

python -m pip install --upgrade pip setuptools wheel
python -m pip install $DEPS
python -m pip install pytest mypy sphinx sphinx-copybutton

for r in $REPOS; do
  python -m pip install --no-deps -e "/workspaces/$r"
done

echo "Ready."
echo "Run tests: python -m pytest /workspaces/nionswift/nion/swift/test/"
echo "Or:        bash /workspaces/nionswift/.devcontainer/run-tests.sh"
