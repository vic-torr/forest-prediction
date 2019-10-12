import os
import glob
import numpy as np
import cv2
import torch
import torchvision
# import rasterio
from torch.utils.data import DataLoader, Dataset
from torch.utils.data.sampler import SubsetRandomSampler
from torchvision import datasets, transforms
from base import BaseDataLoader
from data_loader import utils

# TODO: put in utils
def get_tile_info(tile):
    """
    Retrieve the year, zoom, x, y from a tile. Example: ly2017_12_1223_2516.png
    """
    tile_items = tile.split('_')
    year = tile_items[0][2:]
    z = tile_items[1]
    x = tile_items[2]
    y = tile_items[3][:-4]
    return int(year), z, x, y

# TODO: put in utils
def open_image(img_path):
    filetype = img_path[-3:]
    assert filetype in ['png', 'npy']
    if filetype == 'npy':
        try:
            img_arr = np.load(img_path)
            if len(img_arr.shape) == 3: # RGB
                img_arr = img_arr.transpose([1,2,0])
                return img_arr / 255.
            elif len(img_arr.shape) == 2: # mask
                # change to binary mask
                nonzero = np.where(img_arr!=0)
                img_arr[nonzero] = 1
                return img_arr
        except:
            print('ERROR', img_path)
            return None
        # return img_arr / 255.
    else:
        # For images transforms.ToTensor() does range to (0.,1.)

        img_arr = cv2.imread(img_path)
        try:
            img_arr = cv2.cvtColor(img_arr, cv2.COLOR_BGR2RGB)
        except:
            print(img_path)
        return cv2.cvtColor(img_arr, cv2.COLOR_BGR2RGB)

def get_img(mask_path, img_dir):
    year, z, x, y = get_tile_info(mask_path.split('/')[-1])
    if 'planet2landsat' in img_dir:
        img_template = os.path.join(img_dir, str(year), 'pl{year}_{z}_{x}_{y}.png')
    elif 'landsat' in img_dir:
        img_template = os.path.join(img_dir, str(year), 'ld{year}_{z}_{x}_{y}.png')
    else:
        img_template = os.path.join(img_dir, str(year), 'pl{year}_{z}_{x}_{y}.npy')
    return img_template.format(year=year, z=z, x=x, y=y)


class PlanetSingleDataset(Dataset):
    """
    Planet 3-month mosaic dataset
    """
    def __init__(self, img_dir, label_dir, years, max_dataset_size):
        """Initizalize dataset.
            Params:
                data_dir: absolute path, string
                years: list of years
                filetype: png or npy. If png it is raw data, if npy it has been preprocessed
        """
        self.img_dir = img_dir
        self.label_dir = label_dir
        self.paths = []
        for year in years:
            imgs_path = os.path.join(label_dir, year)
            self.paths.extend(glob.glob(os.path.join(imgs_path, '*')))
        self.paths = self.paths[:min(len(self.paths), max_dataset_size)]
        self.paths.sort()
        # TODO: update mean/std
        self.transforms = transforms.Compose([
            transforms.ToTensor(),
            utils.Normalize((0.3326, 0.3570, 0.2224),
                (0.1059, 0.1086, 0.1283))
        ])
        self.dataset_size = len(self.paths)

    def __len__(self):
        # print('Planet Dataset len called')
        return self.dataset_size

    def __getitem__(self, index):
        r"""Returns data point and its binary mask"""
        # Notes: tiles in annual mosaics need to be divided by 255.
        mask_path = self.paths[index]
        year, z, x, y = get_tile_info(mask_path.split('/')[-1])
        # For img_dir give
        # /mnt/ds3lab-scratch/lming/data/min_quality11/landsat/min_pct
        img_path = get_img(mask_path, self.img_dir)

        mask_arr = open_image(mask_path)
        img_arr = open_image(img_path)
        mask_arr = torch.from_numpy(mask_arr).unsqueeze(0)
        img_arr = self.transforms(img_arr)

        return img_arr.float(), mask_arr.float()

class PlanetDataLoader(BaseDataLoader):
    def __init__(self, img_dir,
            label_dir,
            batch_size,
            years,
            max_dataset_size=float('inf'),
            shuffle=True,
            num_workers=16):
        if max_dataset_size == 'inf':
            max_dataset_size = float('inf')
        self.dataset = PlanetSingleDataset(img_dir, label_dir, years, max_dataset_size)
        super().__init__(self.dataset, batch_size, shuffle, 0, num_workers)

def get_immediate_subdirectories(a_dir):
    return [name for name in os.listdir(a_dir) if os.path.isdir(os.path.join(a_dir, name))]

class PlanetSingleVideoDataset(Dataset):
    """
    Planet 3-month mosaic dataset
    """
    # def __init__(self, img_dir, label_dir, years, max_dataset_size):
    def __init__(self, img_dir, label_dir, video_dir, max_dataset_size):
        """Initizalize dataset.
            Params:
                filetype: png or npy. If png it is raw data, if npy it has been preprocessed
        """
        self.years = ['2013', '2014', '2015', '2016', '2017']
        # self.img_dir = '/mnt/ds3lab-lming/data/min_quality11/landsat/min_pct'
        # self.video_dir = '/mnt/ds3lab-lming/forest-prediction/video_prediction/landsat_video_prediction_results/ours_deterministic_l1'
        # self.label_dir = '/mnt/ds3lab-lming/data/min_quality11/forest_cover/processed'
        self.img_dir = img_dir
        self.label_dir = label_dir
        self.video_dir = video_dir
        self.paths = get_immediate_subdirectories(self.video_dir)
        print('SELF PATTHSSS',self.paths, self.video_dir)
        self.paths.sort()
        # TODO: update mean/std
        self.transforms = transforms.Compose([
            transforms.ToTensor(),
            utils.Normalize((0.3326, 0.3570, 0.2224),
                (0.1059, 0.1086, 0.1283))
        ])
        self.dataset_size = len(self.paths)

    def get_item(self, index):
        key = self.paths[index]
        img_gt_template = os.path.join(self.img_dir, '{year_dir}', 'ld{year_f}_{key}.png')
        img_video_template = os.path.join(self.video_dir, key, 'gen_image_00000_00_0{}.png')
        label_template = os.path.join(self.label_dir, '{year_dir}', 'fc{year_f}_{key}.npy')

        img2013 = img_gt_template.format(year_dir=2013, year_f=2013, key=key)
        img2014 = img_gt_template.format(year_dir=2014, year_f=2014, key=key)
        img2015 = img_video_template.format(0)
        img2016 = img_video_template.format(1)
        img2017 = img_video_template.format(2)

        label2013 = label_template.format(year_dir=2013, year_f=2013, key=key)
        label2014 = label_template.format(year_dir=2014, year_f=2014, key=key)
        label2015 = label_template.format(year_dir=2015, year_f=2015, key=key)
        label2016 = label_template.format(year_dir=2016, year_f=2016, key=key)
        label2017 = label_template.format(year_dir=2017, year_f=2017, key=key)

        return {
            '2013': {
                'img_dir': img2013,
                'label_dir': label2013
            },
            '2014': {
                'img_dir': img2014,
                'label_dir': label2014
            },
            '2015': {
                'img_dir': img2015,
                'label_dir': label2015
            },
            '2016': {
                'img_dir': img2016,
                'label_dir': label2016
            },
            '2017': {
                'img_dir': img2017,
                'label_dir': label2017
            }
        }

    def _process_img_pair(self, img_dict):
        img_arr = open_image(img_dict['img_dir'])
        mask_arr = open_image(img_dict['label_dir'])
        img_arr = self.transforms(img_arr)
        mask_arr = torch.from_numpy(mask_arr).unsqueeze(0)

        return {
            'img_arr': img_arr.float(),
            'mask_arr': mask_arr.float()
        }

    def __len__(self):
        # print('Planet Dataset len called')
        return self.dataset_size

    def __getitem__(self, index):
        r"""Returns data point and its binary mask"""
        # Notes: tiles in annual mosaics need to be divided by 255.
        imgs_dict = self.get_item(index)
        tensor_dict = {
            '2013': self._process_img_pair(imgs_dict['2013']),
            '2014': self._process_img_pair(imgs_dict['2014']),
            '2015': self._process_img_pair(imgs_dict['2015']),
            '2016': self._process_img_pair(imgs_dict['2016']),
            '2017': self._process_img_pair(imgs_dict['2017'])
        }
        return tensor_dict


class PlanetVideoDataLoader(BaseDataLoader):
    def __init__(self, img_dir,
            label_dir,
            video_dir,
            batch_size,
            max_dataset_size=float('inf'),
            shuffle=False,
            num_workers=16):
        self.dataset = PlanetSingleVideoDataset(img_dir, label_dir, video_dir, max_dataset_size)
        super().__init__(self.dataset, batch_size, shuffle, 0, num_workers)
