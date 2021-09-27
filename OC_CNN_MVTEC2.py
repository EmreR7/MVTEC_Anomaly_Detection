import itertools
import os
import pathlib
import random

import keras
import matplotlib.pyplot as plt
import numpy as np
import tensorflow as tf
from sklearn.metrics import roc_curve, auc
from tensorflow.keras.applications import VGG16
from tensorflow.keras.layers import *
from tensorflow.python.data.ops.dataset_ops import AUTOTUNE


def set_seed(seed):
    tf.random.set_seed(seed)
    os.environ['PYTHONHASHSEED'] = str(seed)
    np.random.seed(seed)
    random.seed(seed)


# DEFINE SOME PARAMETERS
train_data_dir = 'C:/Users/Emre/PycharmProjects/Mnist_CNN_Test/carpet/train/'
test_data_dir = 'C:/Users/Emre/PycharmProjects/Mnist_CNN_Test/carpet/test'
SHAPE = (512, 512, 3)
batch_size = 32
set_seed(33)
patch_size = 32
img_height = 512
img_width = 512

# # Get data
# train_ds = tf.keras.preprocessing.image_dataset_from_directory(
#     train_data_dir,
#     image_size=(SHAPE[0], SHAPE[1]),
#     batch_size=batch_size)
#
# test_ds = tf.keras.preprocessing.image_dataset_from_directory(
#     test_data_dir,
#     image_size=(SHAPE[0], SHAPE[1]),
#     batch_size=batch_size)
#
# normalization_layer = tf.keras.layers.experimental.preprocessing.Rescaling(1./255)
# # Normalize the train dataset
# normalized_train_ds = train_ds.map(lambda x, y: (normalization_layer(x), y))
# train_images_batch, train_labels_batch = next(iter(normalized_train_ds))
# train_images_batch = train_images_batch.numpy()
# train_labels_batch = train_labels_batch.numpy()
# print("Shape of train images:", train_images_batch.shape)
# class_names = train_ds.class_names
# print(class_names)
#
# # Normalize the test dataset
# normalized_test_ds = test_ds.map(lambda x, y: (normalization_layer(x), y))
# test_images_batch, test_labels_batch = next(iter(normalized_train_ds))
# test_images_batch = test_images_batch.numpy()
# test_labels_batch = test_labels_batch.numpy()
# print("Shape of test images:", test_images_batch.shape)

train_ds = tf.data.Dataset.list_files(str(pathlib.Path(train_data_dir + '*.png')))


def get_label(file_path):
    # convert the path to a list of path components
    parts = tf.strings.split(file_path, os.path.sep)

    label = 0
    return label


def decode_img(img):
    # convert the compressed string to a 3D uint8 tensor
    img = tf.io.decode_png(img, channels=3)
    # resize the image to the desired size
    return tf.image.resize(img, [img_height, img_width])


def process_path_test_ds(file_path):
    label = get_label(file_path)
    # load the raw data from the file as a string
    img = tf.io.read_file(file_path)
    img = decode_img(img)
    img = tf.cast(img, tf.float32) / 255.0
    return img, label


def process_path_train_ds(file_path):
    # load the raw data from the file as a string
    img = tf.io.read_file(file_path)
    img = decode_img(img)
    img = tf.cast(img, tf.float32) / 255.0
    return img


def configure_for_performance(ds):
    ds = ds.cache()
    ds = ds.shuffle(buffer_size=1000)
    ds = ds.batch(batch_size)
    ds = ds.prefetch(buffer_size=AUTOTUNE)
    return ds


# Set `num_parallel_calls` so multiple images are loaded/processed in parallel.
train_ds = train_ds.map(process_path_train_ds, num_parallel_calls=AUTOTUNE)


def get_patches(images, patch_size):
    all_patches = []
    for rgb_image in images:
        rgb_image = rgb_image.numpy()
        patches = rgb_image.reshape((rgb_image.shape[0] // patch_size,
                                     patch_size, rgb_image.shape[1] // patch_size,
                                     patch_size, 3)).swapaxes(1, 2).reshape((-1, patch_size, patch_size, 3))
        all_patches.extend(patches)

    return all_patches


def vgg_feature_extractor(dataset):
    vgg = VGG16(weights='imagenet', include_top=False, input_shape=(32, 32, 3))
    vgg.trainable = False
    vgg_out = vgg.output
    my_vgg = tf.keras.Model(inputs=vgg.input, outputs=vgg_out)
    features = my_vgg.predict(dataset)
    print("Shape of extracted features: ", features.shape)
    return features


def my_model():
    model = tf.keras.Sequential([
        tf.keras.layers.InputLayer((1, 1, 512)),
        tf.keras.layers.Flatten(),
        tf.keras.layers.Dense(512, activation='relu'),
        tf.keras.layers.Dense(128, activation='relu'),
        tf.keras.layers.Dense(1, activation='sigmoid'),
    ])

    return model


def train_step(batch):
    batch_shape = tf.shape(batch)
    noise = tf.random.normal(shape=batch_shape, stddev=0.1)
    new_batch = tf.concat([batch, noise], axis=0)
    new_labels = tf.concat([tf.zeros(shape=(batch_shape[0], 1)), tf.ones(shape=(batch_shape[0], 1))], axis=0)

    with tf.GradientTape() as tape:
        preds = model(new_batch, training=True)
        loss = tf.reduce_sum(tf.keras.losses.binary_crossentropy(new_labels, preds))
        grad = tape.gradient(loss, model.trainable_variables)
        optimizer.apply_gradients(zip(grad, model.trainable_variables))

    train_acc_metric.update_state(new_labels, preds)
    train_loss_metric.update_state(new_labels, preds)


def train(dataset, epochs):
    for epoch in range(epochs):
        print("\nStart of epoch %d" % (epoch,))
        for batch in dataset:
            train_step(batch)

        train_acc = train_acc_metric.result()
        train_loss = train_loss_metric.result()
        print("Training acc over epoch: %.4f" % (float(train_acc),))
        print("Training loss over epoch: %.4f" % (float(train_loss),))
        train_acc_metric.reset_states()


def get_inference_model(my_model):
    vgg = VGG16(weights='imagenet', include_top=False, input_shape=(32, 32, 3))
    vgg.trainable = False
    vgg_out = vgg.output
    my_inference_model = tf.keras.Model(inputs=vgg.input, outputs=my_model(vgg_out))
    my_inference_model.compile(optimizer=optimizer, loss=keras.losses.binary_crossentropy, metrics=['accuracy'])

    return my_inference_model


model = my_model()
optimizer = tf.keras.optimizers.Adam(lr=1e-4)
# Prepare the metrics.
train_acc_metric = keras.metrics.BinaryAccuracy()
train_loss_metric = keras.metrics.BinaryCrossentropy()

train_ds_patches = get_patches(train_ds, patch_size)
train_ds_patches = np.asarray(train_ds_patches)


# test_images_patches = get_patches(test_images_batch, patch_size)
# test_images_patches = np.asarray(test_images_patches)
# print("Shape of test images in patches:", test_images_patches.shape)

train_ds_features = vgg_feature_extractor(train_ds_patches)
train_ds_patches = tf.data.Dataset.from_tensor_slices(train_ds_features)
train_ds_patches = configure_for_performance(train_ds_patches)
train(train_ds_patches, 3)

model.summary()

# SWITCH TO INFERENCE MODE TO COMPUTE PREDICTIONS
inference_model = get_inference_model(model)
inference_model.summary()
print("Shape of valid labels: ", test_labels_batch.shape)

# COMPUTE PREDICTIONS ON TEST DATA
print("Shape of valid images: ", test_images_patches.shape)
pred_test = inference_model.predict(test_images_patches).ravel()
fpr_keras, tpr_keras, thresholds_keras = roc_curve(test_labels_batch, pred_test, pos_label=1)
auc_keras = auc(fpr_keras, tpr_keras)

plt.figure(1)
plt.plot([0, 1], [0, 1], 'k--')
plt.plot(fpr_keras, tpr_keras, label='OC_CNN (area = {:.3f})'.format(auc_keras))
plt.xlabel('False positive rate')
plt.ylabel('True positive rate')
plt.title('ROC curve')
plt.legend(loc='best')
plt.show()

# Zoom in view of the upper left corner.
plt.figure(2)
plt.xlim(0, 0.2)
plt.ylim(0.8, 1)
plt.plot([0, 1], [0, 1], 'k--')
plt.plot(fpr_keras, tpr_keras, label='OC_CNN (area = {:.3f})'.format(auc_keras))
plt.xlabel('False positive rate')
plt.ylabel('True positive rate')
plt.title('ROC curve (zoomed in at top left)')
plt.legend(loc='best')
plt.show()