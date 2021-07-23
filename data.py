import os
from torch.utils.data import Dataset
import numpy as np
from torchvision import transforms
from PIL import Image
import shutil
import json
import glob
import warnings
import cv2
warnings.filterwarnings("ignore")


def calculate_dataset_stats(path, num_channels, f):
    """This function calculates and returns the mean and std of an image dataset.
    Should be used to determine values for normalization for transforms.

    :param path: the path to the dataset.
    :param num_channels: the number of channels (ie. 1, 3).
    :param f: True if using artificial dataset

    :return: two num_channels length lists, one containing the mean and one
             containing the std."""

    if f:
        classes = ['']
    else:
        classes = [d for d in os.listdir(path) if os.path.isdir(os.path.join(path, d))]

    pixel_num = 0
    channel_sum = np.zeros(num_channels)
    channel_sum_squared = np.zeros(num_channels)

    for idx, d in enumerate(classes):
        im_paths = glob.glob(os.path.join(path, d, "*.png"))
        for path in im_paths:
            im = cv2.imread(path)   # image in M*N*CHANNEL_NUM shape, channel in BGR order
            im = im / 255.0
            pixel_num += (im.size / num_channels)
            channel_sum = channel_sum + np.sum(im, axis=(0, 1))
            channel_sum_squared = channel_sum_squared + np.sum(np.square(im), axis=(0, 1))

    bgr_mean = channel_sum / pixel_num
    bgr_std = np.sqrt(channel_sum_squared / pixel_num - np.square(bgr_mean))

    # change the format from bgr to rgb
    rgb_mean = list(bgr_mean)[::-1]
    rgb_std = list(bgr_std)[::-1]

    return rgb_mean, rgb_std


class GeirhosStyleTransferDataset(Dataset):
    """A custom Dataset class for the Geirhos Style Transfer dataset."""

    def __init__(self, shape_dir, texture_dir, transform=None):
        """
        :param shape_dir: a directory for the style transfer dataset organized by shape
        :param texture_dir: a directory for the style transfer dataset organized by texture
        :param transform: a set of image transformations (optional)
        """

        self.shape_dir = shape_dir
        self.texture_dir = texture_dir
        self.shape_classes = {}

        # Default image processing
        if transform is None:
            rgb_mean, rgb_std = calculate_dataset_stats('stimuli-shape/style-transfer', 3, False)

            self.transform = transforms.Compose([
                transforms.Resize(224),
                transforms.ToTensor(),
                transforms.Normalize(mean=rgb_mean, std=rgb_std)
            ])
        else:
            self.transform = transform

        # Create/load dictionaries containing shape and texture classifications for each image
        try:
            # Load dictionary
            self.shape_classes = json.load(open('geirhos_shape_classes.json'))

        except FileNotFoundError:
            # Create dictionary
            for image_dir in glob.glob('stimuli-shape/style-transfer/*/*.png'):
                image = image_dir.split('/')
                shape = image[2]  # Shape class of image
                texture_spec = image[3].split('-')[1].replace('.png', '')  # Specific texture instance, eg. clock2
                shape_spec = image[3].split('-')[0]  # Specific shape instance, eg. airplane1
                texture = ''.join([i for i in texture_spec if not i.isdigit()])  # Texture class

                if shape != texture:  # Filter images that are not cue-conflict
                    self.shape_classes[image[3]] = {}  # Initialize dictionary for single image
                    self.shape_classes[image[3]]['shape'] = shape
                    self.shape_classes[image[3]]['texture'] = texture
                    self.shape_classes[image[3]]['shape_spec'] = shape_spec
                    self.shape_classes[image[3]]['texture_spec'] = texture_spec
                    self.shape_classes[image[3]]['dir'] = image_dir

            # Save dictionary as a JSON file
            with open('geirhos_shape_classes.json', 'w') as file:
                json.dump(self.shape_classes, file)

    def __len__(self):
        """
        :return: the number of images in the style transfer dataset.
        """

        return len(self.shape_classes.keys()) # Number of images

    def __getitem__(self, idx):
        """
        :param idx: the index of the image to be accessed
        :return: a tuple with the idx_th image itself with transforms applied, the name of the
        idx_th image, its shape category, its texture category, its specific shape,
        specific texture.
        """

        images = sorted([key for key in self.shape_classes.keys()])

        image_name = images[idx]  # Name of PNG file
        im_dict = self.shape_classes[image_name]  # Dictionary with properties for this image
        image_dir = im_dict['dir']  # Full path to image file

        image = Image.open(image_dir)  # Load image

        #image.show()

        if self.transform:
            image = self.transform(image)

        shape = im_dict['shape']
        texture = im_dict['texture']
        shape_spec = im_dict['shape_spec']
        texture_spec = im_dict['texture_spec']

        return image, image_name, shape, texture, shape_spec, texture_spec

    def create_texture_dir(self, shape_dir, texture_dir):
        """Takes a dataset that is organized by shape category and copies
        images into folders organized by texture category.

        :param shape_dir: the directory of the shape-based dataset.
        :param texture_dir: name of the directory for the texture-based version."""

        texture_path = texture_dir + '/' + shape_dir.split('/')[1]

        try:
            shutil.rmtree(texture_dir)
            os.mkdir(texture_dir)
            os.mkdir(texture_path)
        except:
            os.mkdir(texture_dir)
            os.mkdir(texture_path)

        for category in sorted(os.listdir(shape_dir)):
            if category != '.DS_Store':
                os.mkdir(texture_path + '/' + category)

        for category in sorted(os.listdir(shape_dir)):
            if category != '.DS_Store':
                for image in sorted(os.listdir(shape_dir + '/' + category)):
                    texture = image.replace('.png','').split('-')[1]
                    texture = ''.join([i for i in texture if not i.isdigit()])

                    shutil.copyfile(shape_dir + '/' + category + '/' + image, texture_path + '/' + texture + '/' + image)


class GeirhosTriplets:
    """This class provides a way to generate and access all possible triplets of
    Geirhos images. These triplets consist of an anchor image (eg. cat4-truck3.png),
    a shape match to the anchor image (eg. cat4-boat2.png), and a texture match to
    the anchor (eg. dog3-truck3.png).

    The shape and texture matches are specific: ie., cat4-truck3.png is a shape match
    for cat4-knife2.png but not for cat2-knife2.png.

    The purpose of these triplets is to measure similarity between shape matches/texture
    matches and the anchor image after having been passed through a model."""

    def __init__(self, shape_dir, transform=None):
        """Generates/loads the triplets. all_triplets is a list of all 3-tuples.
        triplets_by_image is a dictionary; the keys are image names, and it stores all
        shape/texture matches plus all possible triplets for a given image (as the anchor).

        :param shape_dir: directory for the Geirhos dataset.
        :param transform: a set of image transformations (optional)
        """

        self.shape_classes = {}
        self.all_triplets = []
        self.triplets_by_image = {}

        # Default image processing
        if transform is None:
            rgb_mean, rgb_std = calculate_dataset_stats('stimuli-shape/style-transfer', 3, False)

            self.transform = transforms.Compose([
                transforms.Resize(224),
                transforms.ToTensor(),
                transforms.Normalize(mean=rgb_mean, std=rgb_std)
            ])
        else:
            self.transform = transform

        # Create/load dictionaries containing shape and texture classifications for each image
        try:
            # Load dictionary
            self.shape_classes = json.load(open('geirhos_shape_classes.json'))

        except FileNotFoundError:
            # Create dictionary
            for image_dir in glob.glob('stimuli-shape/style-transfer/*/*.png'):
                image = image_dir.split('/')
                shape = image[2]  # Shape class of image
                texture_spec = image[3].split('-')[1].replace('.png', '')  # Specific texture instance, eg. clock2
                shape_spec = image[3].split('-')[0]  # Specific shape instance, eg. airplane1
                texture = ''.join([i for i in texture_spec if not i.isdigit()])  # Texture class

                if shape != texture:  # Filter images that are not cue-conflict
                    self.shape_classes[image[3]] = {}  # Initialize dictionary for single image
                    self.shape_classes[image[3]]['shape'] = shape
                    self.shape_classes[image[3]]['texture'] = texture
                    self.shape_classes[image[3]]['shape_spec'] = shape_spec
                    self.shape_classes[image[3]]['texture_spec'] = texture_spec
                    self.shape_classes[image[3]]['dir'] = image_dir

            # Save dictionary as a JSON file
            with open('geirhos_shape_classes.json', 'w') as file:
                json.dump(self.shape_classes, file)

        # Generate/load triplets
        try:
            # Load triplets
            self.triplets_by_image = json.load(open('geirhos_triplets.json'))
            self.all_triplets = self.triplets_by_image['all']
            self.triplets_by_image.pop('all')

        except FileNotFoundError:
            # Generate triplets
            self.all_triplets = []

            for image in self.shape_classes.keys(): # Iterate over anchor images
                shape = self.shape_classes[image]['shape']
                shape_spec = self.shape_classes[image]['shape_spec']
                texture_spec = self.shape_classes[image]['texture_spec']

                self.triplets_by_image[image] = {}
                self.triplets_by_image[image]['shape matches'] = []
                self.triplets_by_image[image]['texture matches'] = []
                self.triplets_by_image[image]['triplets'] = []

                for shape_match in glob.glob(shape_dir + '/' + shape + '/' + shape_spec + '*.png'):
                    shape_match = shape_match.split('/')[-1]
                    if shape_match == image or shape_match not in self.shape_classes.keys():
                        continue
                    self.triplets_by_image[image]['shape matches'].append(shape_match)
                for texture_match in glob.glob(shape_dir + '/*/*' + texture_spec + '.png'):
                    texture_match = texture_match.split('/')[-1]
                    if texture_match == image or texture_match not in self.shape_classes.keys():
                        continue
                    self.triplets_by_image[image]['texture matches'].append(texture_match)

                for shape_match in self.triplets_by_image[image]['shape matches']:
                    for texture_match in self.triplets_by_image[image]['texture matches']:
                        triplet = [image, shape_match, texture_match]
                        self.triplets_by_image[image]['triplets'].append(triplet)
                        self.all_triplets.append(triplet)

            self.triplets_by_image['all'] = self.all_triplets

            # Save dictionary as a JSON file
            with open('geirhos_triplets.json', 'w') as file:
                json.dump(self.triplets_by_image, file)

    def getitem(self, triplet):
        """For a given (anchor, shape match, texture match) triplet, loads and returns
        all 3 images.

        :param triplet: a length-3 list containing the name of an anchor, shape match,
            and texture match.
        :return: the anchor, shape match, and texture match images with transforms applied."""

        anchor_path = self.shape_classes[triplet[0]]['dir']
        shape_path = self.shape_classes[triplet[1]]['dir']
        texture_path = self.shape_classes[triplet[2]]['dir']

        # Load images
        anchor_im = Image.open(anchor_path)
        shape_im = Image.open(shape_path)
        texture_im = Image.open(texture_path)

        # Apply transforms
        if self.transform:
            anchor_im = self.transform(anchor_im)
            shape_im = self.transform(shape_im)
            texture_im = self.transform(texture_im)

        return anchor_im.unsqueeze(0), shape_im.unsqueeze(0), texture_im.unsqueeze(0)


class FakeStimTrials:
    """This class provides a way to generate and access all possible trials of novel,
    artificial stimuli from the stimuli-shape/fake directory. Each stimulus consists of
    a shape, color, and texture. A trial consists of an anchor image, a shape match, a
    color match, and a texture match."""

    def __init__(self, fake_dir='stimuli-shape/fake', transform=None):
        """Generates/loads all possible trials. all_trials is a list of all 4-tuples.
        trials_by_image is a dictionary; the keys are the image paths, and it stores
        all shape/color/texture matches plus all possible trials for the given image
        as the anchor.

        :param fake_dir: directory for fake images
        :param transform: transforms to be applied"""

        self.all_stims = {}  # Contains shape, texture, & color classifications for all images
        self.all_trials = []
        self.trials_by_image = {}

        # Default image processing
        if transform is None:
            rgb_mean, rgb_std = calculate_dataset_stats('stimuli-shape/fake', 3, True)

            self.transform = transforms.Compose([
                transforms.Resize(224),
                transforms.ToTensor(),
                transforms.Normalize(mean=rgb_mean, std=rgb_std)
            ])
        else:
            self.transform = transform

        # Create/load dictionaries containing shape/texture/color classifications for each image
        try:
            # Load dictionaries
            self.all_stims = json.load(open('fake_stimulus_classes.json'))  # Dictionary of dictionaries

        except FileNotFoundError:

            # Create dictionaries
            for image_dir in glob.glob(fake_dir + '/*.png'):
                image = image_dir.split('/')[2]  # file name
                specs = image.replace('.png', '').split('_')  # [shape, texture, color]

                if 'x' in specs or 'X' in specs:
                    os.remove(image_dir)
                    continue
                else:
                    self.all_stims[image] = {}
                    self.all_stims[image]['shape'] = specs[0]
                    self.all_stims[image]['texture'] = specs[1]
                    self.all_stims[image]['color'] = specs[2]
                    self.all_stims[image]['dir'] = image_dir

            # Save dictionary as a JSON file
            with open('fake_stimulus_classes.json', 'w') as file:
                json.dump(self.all_stims, file)

        # Generate/load trials
        try:
            # Load trials
            self.trials_by_image = json.load(open('fake_trials.json'))
            self.all_trials = self.trials_by_image['all']
            self.trials_by_image.pop('all')

        except FileNotFoundError:

            # Generate trials
            for image in self.all_stims.keys():  # Iterate over anchor images
                shape = self.all_stims[image]['shape']
                texture = self.all_stims[image]['texture']
                color = self.all_stims[image]['color']

                self.trials_by_image[image] = {}
                self.trials_by_image[image]['shape matches'] = []
                self.trials_by_image[image]['texture matches'] = []
                self.trials_by_image[image]['color matches'] = []
                self.trials_by_image[image]['trials'] = []

                # Find shape/texture/color matches
                for shape_match in self.all_stims.keys():
                    shape2 = self.all_stims[shape_match]['shape']
                    texture2 = self.all_stims[shape_match]['texture']
                    color2 = self.all_stims[shape_match]['color']
                    if shape_match == image or shape != shape2:  # Same image or different shape
                        continue
                    elif texture == texture2 or color == color2:  # Same texture or color
                        continue
                    self.trials_by_image[image]['shape matches'].append(shape_match)
                for texture_match in self.all_stims.keys():
                    shape2 = self.all_stims[texture_match]['shape']
                    texture2 = self.all_stims[texture_match]['texture']
                    color2 = self.all_stims[texture_match]['color']
                    if texture_match == image or texture != texture2:
                        continue
                    elif shape == shape2 or color == color2:
                        continue
                    self.trials_by_image[image]['texture matches'].append(texture_match)
                for color_match in self.all_stims.keys():
                    shape2 = self.all_stims[color_match]['shape']
                    texture2 = self.all_stims[color_match]['texture']
                    color2 = self.all_stims[color_match]['color']
                    if color_match == image or color != color2:
                        continue
                    elif shape == shape2 or texture == texture2:
                        continue
                    self.trials_by_image[image]['color matches'].append(color_match)

                # Create trials
                for shape_match in self.trials_by_image[image]['shape matches']:
                    for texture_match in self.trials_by_image[image]['texture matches']:
                        if texture_match == shape_match:
                            continue
                        for color_match in self.trials_by_image[image]['color matches']:
                            if color_match == texture_match or color_match == shape_match:
                                continue
                            trial = [image, shape_match, texture_match, color_match]
                            self.trials_by_image[image]['trials'].append(trial)
                            self.all_trials.append(trial)

            self.trials_by_image['all'] = self.all_trials

            # Save dictionary as a JSON file
            with open('fake_trials.json', 'w') as file:
                json.dump(self.trials_by_image, file)

    def getitem(self, trial):
        """For a given (anchor, shape match, texture match, color match) trial, loads and returns
        all 4 images. For a given singular index, returns just that image corresponding to that
        index.

        :param trial: a length-4 list containing the name of an anchor, shape match, texture match,
            and color match (self.all_trials is a list of such lists) OR a singular integer index.
        :return: the anchor, shape match, texture match, and color match images with transforms
            applied."""

        if isinstance(trial, int):
            name = list(self.all_stims.keys())[trial]
            path = self.all_stims[name]['dir']

            im = Image.open(path).convert('RGB')

            if self.transform:
                im = self.transform(im)

            return im, name

        else:
            anchor_path = self.all_stims[trial[0]]['dir']
            shape_path = self.all_stims[trial[1]]['dir']
            texture_path = self.all_stims[trial[2]]['dir']
            color_path = self.all_stims[trial[3]]['dir']

            # Load images
            anchor_im = Image.open(anchor_path)
            shape_im = Image.open(shape_path)
            texture_im = Image.open(texture_path)
            color_im = Image.open(color_path)

            # Apply transforms
            if self.transform:
                anchor_im = self.transform(anchor_im)
                shape_im = self.transform(shape_im)
                texture_im = self.transform(texture_im)
                color_im = self.transform(color_im)

            return anchor_im.unsqueeze(0), shape_im.unsqueeze(0), texture_im.unsqueeze(0), color_im.unsqueeze(0)