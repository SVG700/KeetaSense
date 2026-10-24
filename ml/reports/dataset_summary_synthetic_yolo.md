# Dataset summary

> **SYNTHETIC DATA** - generated test images, not real insects.

- Created: 2026-10-25T01:22:43
- Converted dataset: `ml\data\synthetic_yolo` (from `ml\data\synthetic_raw`, format voc)
- Images: **80**, labelled objects: **2314**
- Image resolution: width 640-640 px, height 640-640 px (most common 640x640)

## Raw labels found

| Raw label | Count | Mapped to |
|---|---|---|
| WF | 1827 | whitefly |
| MR | 246 | macrolophus |
| NC | 241 | nesidiocoris |

## Splits

| Split | Images | Objects |
|---|---|---|
| train | 56 | 1667 |
| val | 12 | 318 |
| test | 12 | 329 |

## Classes

| Class | Objects | Share | Train / Val / Test | Insect size px (median, p10-p90) |
|---|---|---|---|---|
| whitefly | 1827 | 79.0% | 1308 / 248 / 271 | 16.0 (14.0-18.0) |
| macrolophus | 246 | 10.6% | 194 / 30 / 22 | 35.0 (30.5-40.0) |
| nesidiocoris | 241 | 10.4% | 165 / 40 / 36 | 41.0 (36.0-47.0) |

## Warnings

- none

Insect size = longer side of the labelled box, in pixels of the original photo. With SAHI 640 px tiles, an insect of N px stays N px for the model.
