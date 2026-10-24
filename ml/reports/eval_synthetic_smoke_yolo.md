# KeetaSense evaluation report

> **SYNTHETIC DATA** - these numbers only show the pipeline runs. They say nothing about accuracy on real insects.

- Created: 2026-10-25T00:46:52
- Dataset: `ml\data\synthetic_yolo\data.yaml`
- Detector: `yolo_sahi` (weights `C:\Users\Samhith V Gupta\Desktop\Samhith\KeetaSense\ml\weights\synthetic_smoke_test.pt`)
- Test images: 12
- IoU threshold: 0.5, confidence threshold: 0.25

## Detection: mAP@0.5 = 0.0

| Class | Category | GT | Pred | TP | Precision | Recall | AP@0.5 |
|---|---|---|---|---|---|---|---|
| whitefly | pest | 271 | 0 | 0 | None | 0.0 | 0.0 |
| macrolophus | predator | 22 | 0 | 0 | None | 0.0 | 0.0 |
| nesidiocoris | predator | 36 | 2 | 0 | 0.0 | 0.0 | 0.0 |

## Counting error (per image)

| Group | Mean true count | MAE | MAPE % | Images used for MAPE |
|---|---|---|---|---|
| whitefly | 22.58 | 22.583 | 100.0 | 12 |
| macrolophus | 1.83 | 1.833 | 100.0 | 6 |
| nesidiocoris | 3.0 | 2.833 | 94.7 | 11 |
| all_pests | 22.58 | 22.583 | 100.0 | 12 |
| all_predators | 4.83 | 4.667 | 94.7 | 11 |
