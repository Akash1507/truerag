#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

terraform -chdir="$ROOT_DIR/terraform/modules/ecs" init -backend=false -input=false >/dev/null
terraform -chdir="$ROOT_DIR/terraform/modules/ecs" validate
terraform fmt -check -recursive "$ROOT_DIR/terraform"
