# Model weights

- `best.pt` - the trained KeetaSense detector. **Not included**: train it on Colab
  (`ml/train_colab.ipynb`) and copy it here. While it is missing, the app runs in
  clearly labelled **DEMO DETECTOR** mode.
- `yolov8n.pt` - COCO-pretrained starting weights (downloaded automatically by `ml/train.py`).
- `synthetic_*.pt` - smoke-test weights trained on SYNTHETIC images only. Useless on real
  insects; they only prove that training and inference run.

`*.pt` files are git-ignored because they are large binary files.
