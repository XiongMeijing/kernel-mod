# -*- coding: utf-8 -*-
"""
Code for running experiments on the CelebA, CIFAR10,LSUN data.

By default, assume the following directory structure:

shared_resource_folder/problems/celeba/
├── data
│   ├── gen_smile.npy
│   ├── gen_nonsmile.npy
│   ├── ref_smile.npy
│   └── ref_smile.npy
├── inception_features
│   ├── gen_smile.npy
│   ├── gen_nonsmile.npy
│   ├── ref_smile.npy
│   └── ref_nonsmile.npy


shared_resource_folder/problems/cifar10/
├── data
│   ├── airplane.npy
│   ├── automobile.npy
│   ├── bird.npy
│   ├── cat.npy
│   ├── deer.npy
│   ├── dog.npy
│   ├── frog.npy
│   ├── horse.npy
│   ├── ship.npy
│   └── truck.npy
├── inception_features
│   ├── airplane.npy
│   ├── automobile.npy
│   ├── bird.npy
│   ├── cat.npy
│   ├── deer.npy
│   ├── dog.npy
│   ├── frog.npy
│   ├── horse.npy
│   ├── ship.npy
│   ├── truck.npy
│   └── wholedata.npy



shared_resource_folder/problems/lsun/
├── data
│   ├── kitchen.npy
│   ├── restaurant.npy
│   ├── confroom.npy
│   ├── bedroom.npy
│   ├── 3212_began.npy
│   ├── 1232_began.npy
│   ├── 3212_dcgan.npy
│   ├── 1232_dcgan.npy
├── inception_features (or alexnet_features)
│   ├── kitchen.npy
│   ├── restaurant.npy
│   ├── confroom.npy
│   ├── bedroom.npy
│   ├── 3212_began.npy
│   ├── 1232_began.npy
│   ├── 1232_dcgan.npy
│   ├── 1232_dcgan.npy

"""

from kmod import util, glo, log
import autograd.numpy as np
import os


class DataLoader(object):

    problem_list = ['cifar10', 'lsun', 'celeba', ]

    def __init__(self, dataname):
        if dataname not in self.problem_list:
            raise ValueError(('The dataset name should be one of {}.'
                              'Was {}').format(self.problem_list, dataname)
                             )
        self.dataname = dataname

    @property
    def classes(self):
        celeba_classes = ['gen_smile', 'gen_nonsmile', 'ref_smile', 'ref_nonsmile']
        cifar10_classes = ['airplane', 'automobile', 'bird', 'cat', 'deer',
                           'dog', 'frog', 'horse', 'ship', 'truck']
        lsun_classes = ['kitchen', 'restaurant', 'confroom', 'bedroom',
                        '3212_began', '1232_began', '3212_dcgan', '1232_dcgan',
                        '3212_dcgan_3',
                        ]
        class_lists = {'celeba': celeba_classes, 'cifar10': cifar10_classes,
                       'lsun': lsun_classes}

        return class_lists[self.dataname]

    @property
    def class_ind_dict(self):
        return dict(zip(self.classes, range(len(self.classes))))

    @property
    def data_folder(self):
        return glo.shared_resource_folder('problems', self.dataname)

    def data_path(self, *relative_path):
        """
        Returns a path relative to the problem directory
        """
        return os.path.join(self.data_folder, *relative_path)

    def load_data_array(self, class_name):
        """
        class_name can be airplane, automobile, ....
        """
        npy_path = self.data_path('data', '{}.npy'.format(class_name))
        array = np.load(npy_path)
        return array

    def load_feature_array(self, class_name, feature_folder='inception_features'):
        """
        class_name can be airplane, automobile, ... or wholedata.
        """
        npy_path = self.data_path(feature_folder, '{}.npy'.format(class_name))
        array = np.load(npy_path)
        return array

    def load_stack(self, class_data_loader, classes=None, seed=28, max_class_size=None):
        """
        This function is deterministic given the seed.

        max_class_size: if specified, then randomly select at most max_class_size
        points in each class.
        """
        if classes is None:
            classes = self.classes
        list_arrays = []
        label_arrays = []
        with util.NumpySeedContext(seed=seed):
            for c in classes:
                log.l().info('Loading {} class: {}'.format(c, self.name))
                arr = class_data_loader(c)
                nc = arr.shape[0]
                if max_class_size is not None:
                    ncmax = min(nc, max_class_size)
                else:
                    ncmax = nc
                Ind = util.subsample_ind(nc, ncmax, seed=seed+3)
                sub_arr = arr[Ind, :]
                class_label = self.class_ind_dict[c]
                Yc = np.ones(ncmax)*class_label

                list_arrays.append(sub_arr)
                label_arrays.append(Yc)
        stack = np.vstack(list_arrays)
        label_stack = np.hstack(label_arrays)
        assert stack.shape[0] <= len(classes)*max_class_size
        assert stack.shape[0] == len(label_stack)
        return stack, label_stack

    def load_stack_data(self, classes=None, seed=28, max_class_size=None):
        """
        Load all the numpy array data (images) in the specified list of classes (as strings).
        If None, load all classes.

        return (X, Y) where X = stack of all the data, Y = one-dim numpy array of class indices
        """
        return self.load_stack(self.load_data_array, classes, seed, max_class_size)

    def load_stack_feature(self, classes=None, seed=28, max_class_size=None):
        """
        Load all the numpy array of features in the specified list of classes (as strings).
        If None, load all classes.

        return (X, Y) where X = stack of all the features, Y = one-dim numpy array of class indices
        """
        return self.load_stack(self.load_feature_array, classes, seed, max_class_size)
