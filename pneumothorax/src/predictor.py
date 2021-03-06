import os
import glob
from tqdm import tqdm
import numpy as np

import albumentations as albu
from albumentations.torch import ToTensor
from torch.utils.data import DataLoader, Dataset  # , sampler
import torch
import cv2

from .utils.logger import log
from .factory import get_transforms


class TestDataset(Dataset):
    def __init__(self, cfg, df, hflip=False):
        self.root = cfg.imgdir
        self.fnames = list(df["ImageId"])
        self.num_samples = len(self.fnames)

        if not hflip:
            _transforms = cfg.transforms
        else:
            _transforms = cfg.transforms_and_hflip
        self.transform = get_transforms(_transforms)

    def __getitem__(self, idx):
        fname = self.fnames[idx]
        path = os.path.join(self.root, fname + ".png")
        image = cv2.imread(path)
        images = self.transform(image=image)["image"]
        return images

    def __len__(self):
        return self.num_samples


def get_dataloader_test(cfg, df, hflip=False):
    dataset = TestDataset(cfg, df, hflip=hflip)
    loader = DataLoader(dataset, **cfg.loader)
    return loader


def get_pixel_probabilities(cfg, model, testset, hflip=False):
    pixel_probabilities = []
    imgsize = 1024  # cfg.data.test.imgsize
    trained_models = glob.glob(cfg.data.test.trained_models)
    log(f'Making predictions on test images using the following models: {trained_models}')
    assert len(trained_models) == cfg.n_fold

    for batch in tqdm(testset):

        for j in range(cfg.n_fold):
            model_checkpoint = torch.load(trained_models[j],
                                          map_location=lambda storage,
                                          loc: storage)
            model.load_state_dict(model_checkpoint["state_dict"])
            if j == 0:
                predictions_ave = torch.sigmoid(model(batch.cuda()))
            else:
                predictions_ave += torch.sigmoid(model(batch.cuda()))

        predictions_ave = predictions_ave / cfg.n_fold
        # (batch_size, 1, size, size) -> (batch_size, size, size)
        predictions_ave = predictions_ave.detach().cpu().numpy()[:, 0, :, :]

        for probability in predictions_ave:
            if probability.shape != (imgsize, imgsize):
                probability = cv2.resize(probability, dsize=(imgsize, imgsize),
                                         interpolation=cv2.INTER_LINEAR)
            if hflip:
                pixel_probabilities.append(np.fliplr(probability))
            else:
                pixel_probabilities.append(probability)

    return pixel_probabilities


def post_process(probability, prob_threshold=0.5, min_object_size=3500,
                 imgsize=1024):
    mask = cv2.threshold(probability, prob_threshold, 1, cv2.THRESH_BINARY)[1]
    num_component, component = cv2.connectedComponents(mask.astype(np.uint8))
    predictions = np.zeros((imgsize, imgsize), np.float32)
    num = 0
    for c in range(1, num_component):
        p = (component == c)
        if p.sum() > min_object_size:
            predictions[p] = 1
            num += 1
    return predictions, num
