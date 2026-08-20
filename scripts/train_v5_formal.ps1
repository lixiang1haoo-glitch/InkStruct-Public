param(
    [int[]]$Seeds = @(1001, 2002, 3003),
    [string]$PythonPath = ".\.venv\Scripts\python.exe"
)

$ErrorActionPreference = "Stop"

foreach ($TrainingSeed in $Seeds) {
    $Checkpoint = "artifacts/models/v5_formal_seed$TrainingSeed.pt"
    & $PythonPath -m inkstruct train `
        --casia-lmdb data/CASIA_CHINESE/train `
        --test-lmdb data/CASIA_CHINESE/test `
        --database artifacts/structures/characters.sqlite3 `
        --output $Checkpoint `
        --steps 10000 `
        --batch-size 8 `
        --max-records 50000 `
        --references 8 `
        --learning-rate 0.0002 `
        --seed $TrainingSeed `
        --split-seed 1001 `
        --save-every 100 `
        --validate-every 20 `
        --validation-episodes 64 `
        --early-stop-patience 5 `
        --early-stop-min-delta 0.0001 `
        --calibrate-episodes 128 `
        --refiner `
        --factorized-style `
        --curve-loss-weight 1.0 `
        --sdf-loss-weight 0.25 `
        --render-sizes 32,64
    if ($LASTEXITCODE -ne 0) {
        throw "Formal training failed for seed $TrainingSeed"
    }
}
