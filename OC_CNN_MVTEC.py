import os
import pathlib
import random

import keras
import matplotlib.pyplot as plt
import numpy as np
import tensorflow as tf
from sklearn.metrics import roc_curve, auc
from sklearn.model_selection import train_test_split
from tensorflow.keras.applications import VGG16
from tensorflow.python.data.ops.dataset_ops import AUTOTUNE


def set_seed(seed):
    tf.random.set_seed(seed)
    os.environ['PYTHONHASHSEED'] = str(seed)
    np.random.seed(seed)
    random.seed(seed)


# train_data_dir = 'dataset/carpet/train/'
# test_data_dir = 'dataset/carpet/test/'
# ground_truth_data_dir = 'dataset/carpet/ground_truth/'

# DEFINE SOME PARAMETERS
train_data_dir = 'dataset/carpet/train/'
test_data_dir = 'dataset/carpet/test/color'
ground_truth_data_dir = 'dataset/carpet/ground_truth/color'
batch_size = 32
epoch = 2
set_seed(33)
patch_size = 32
img_height = 512
img_width = 512


def get_labels(dataset):
    labels = []
    for image in dataset:
        if np.any(image > 0):
            labels.append(1)
        else:
            labels.append(0)
    labels = np.asarray(labels)
    return labels


def remove_excessive_normal_images(test_dataset, ground_truth_dataset, labels):
    my_list = []
    counter = 0
    anomaly_count = 0
    for image in ground_truth_dataset:
        if np.any(image > 0):
            anomaly_count += 1

    for image in ground_truth_dataset:
        if np.all(image == 0):
            my_list.append(counter)
        counter += 1
        if len(my_list) >= ground_truth_dataset.shape[0] - 2 * anomaly_count:
            break
    new_dataset = np.delete(test_dataset, my_list, axis=0)
    new_labels = np.delete(labels, my_list, axis=0)
    return new_dataset, new_labels


def decode_img(img):
    # convert the compressed string to a 3D uint8 tensor
    img = tf.io.decode_png(img, channels=3)
    # resize the image to the desired size
    return tf.image.resize(img, [img_height, img_width])


def process_path(file_path):
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


def train_step(step, batch):
    batch_shape = tf.shape(batch)
    noise = tf.random.normal(shape=batch_shape, stddev=5.0)
    new_batch = tf.concat([batch, noise], axis=0)
    new_labels = tf.concat([tf.zeros(shape=(batch_shape[0], 1)), tf.ones(shape=(batch_shape[0], 1))], axis=0)

    with tf.GradientTape() as tape:
        preds = model(new_batch, training=True)
        loss = tf.reduce_sum(tf.keras.losses.binary_crossentropy(new_labels, preds))
        grad = tape.gradient(loss, model.trainable_variables)
        optimizer.apply_gradients(zip(grad, model.trainable_variables))

    train_acc_metric.update_state(new_labels, preds)

    # Log every 200 batches.
    if step % 200 == 0:
        print(
            "Training loss (for one batch) at step %d: %.4f"
            % (step, float(loss))
        )
        print("Seen so far: %d samples" % ((step + 1) * batch_size))


def train(dataset, epochs):
    for epoch in range(epochs):
        print("\nStart of epoch %d" % (epoch,))
        for step, batch in enumerate(dataset):
            train_step(step, batch)

        train_acc = train_acc_metric.result()
        print("Training acc over epoch: %.4f" % (float(train_acc),))
        train_acc_metric.reset_states()


def get_inference_model(my_model):
    vgg = VGG16(weights='imagenet', include_top=False, input_shape=(32, 32, 3))
    vgg.trainable = False
    vgg_out = vgg.output
    my_inference_model = tf.keras.Model(inputs=vgg.input, outputs=my_model(vgg_out))
    # my_inference_model.compile(optimizer=optimizer, loss=keras.losses.binary_crossentropy, metrics=['accuracy'])

    return my_inference_model


model = my_model()
optimizer = tf.keras.optimizers.Adam(lr=1e-4)
# Prepare the metrics.
train_acc_metric = keras.metrics.BinaryAccuracy()

train_ds = tf.data.Dataset.list_files(str(pathlib.Path(train_data_dir + '*.png')))

# Set `num_parallel_calls` so multiple images are loaded/processed in parallel.
train_ds = train_ds.map(process_path, num_parallel_calls=AUTOTUNE)
train_ds_patches = get_patches(train_ds, patch_size)
train_ds_patches = np.asarray(train_ds_patches)
print("Shape of train dataset: ", train_ds_patches.shape)

# Get the ground truth dataset for labeling the images/patches
ground_truth_ds = tf.data.Dataset.list_files(str(pathlib.Path(ground_truth_data_dir + '*.png')), shuffle=False)
for f in ground_truth_ds.take(10):
    print(f.numpy())
ground_truth_ds = ground_truth_ds.map(process_path, num_parallel_calls=AUTOTUNE)
ground_truth_ds = get_patches(ground_truth_ds, patch_size)
ground_truth_ds = np.asarray(ground_truth_ds)
print("Shape of ground truth dataset: ", ground_truth_ds.shape)



test_labels = get_labels(ground_truth_ds)
print("Shape of test labels: ", test_labels.shape)

# Get the test dataset
test_ds = tf.data.Dataset.list_files(str(pathlib.Path(test_data_dir + '*.png')), shuffle=False)
for f in test_ds.take(10):
    print(f.numpy())
test_ds = test_ds.map(process_path, num_parallel_calls=AUTOTUNE)
test_ds = get_patches(test_ds, patch_size)
test_ds = np.asarray(test_ds)
print("Shape of test dataset", test_ds.shape)

# plt.figure(figsize=(30, 30))
# for i in range(256):
#     # define subplot
#     plt.subplot(16, 16, i + 1)
#     # plot raw pixel data
#     image = ground_truth_ds[i]
#     # if test_labels[i] == 1:
#        # image[0:32, :, 0] = 0.9  # 1 entspricht 255
#     plt.imshow(image)
#     plt.title(test_labels[i])
#     plt.axis("off")
# # show the figure
# plt.show()

# labelposindex = 0
# plt.figure(figsize=(10, 10))
# for images in test_ds:
#     ax = plt.subplot(16, 16, 3)
#     plt.imshow(images)
#     plt.title(test_labels[labelposindex])
#     plt.axis("off")
#     plt.show()
#     labelposindex += 1

plt.figure(figsize=(30, 30))
for i in range(256):
    # define subplot
    plt.subplot(16, 16, i + 1)
    # plot raw pixel data
    image = test_ds[i]
    if test_labels[i] == 1:
        image[0:32, :, 0] = 0.9  # 1 entspricht 255
    plt.imshow(image)
    plt.title(test_labels[i])
    plt.axis("off")
# show the figure
plt.show()



# Shuffle the test data
# rand_idx = np.arange(test_ds.shape[0])
# np.random.shuffle(rand_idx)
# test_ds = test_ds[rand_idx]
# test_labels = test_labels[rand_idx]


# check if image and label are correctly binded
# counter = 0
# for label in valid_labels:
#     if label == 1:
#         # plot raw pixel data
#         plt.imshow(valid_ds[counter])
#         print(valid_labels[counter])
#         # show the figure
#         plt.show()
#     counter += 1

train_ds_features = vgg_feature_extractor(train_ds_patches)
# delete_train_my_list = np.arange(68680)
# train_ds_features = np.delete(train_ds_features, delete_train_my_list, axis=0)
# print("Shape of reduced train dataset:", train_ds_features.shape)
train_ds_patches = tf.data.Dataset.from_tensor_slices(train_ds_features)
train_ds_patches = configure_for_performance(train_ds_patches)

train(train_ds_patches, epoch)

model.summary()

# Switch to inference mode to compute predictions
inference_model = get_inference_model(model)
inference_model.summary()

# compute predictions on test data
pred_test = (inference_model.predict(test_ds) > 0.0005260525).astype("int32").ravel()
#pred_test = inference_model.predict(test_ds).ravel()
print(pred_test)
plt.figure(figsize=(30, 30))
for i in range(256):
    # define subplot
    plt.subplot(16, 16, i + 1)
    # plot raw pixel data
    image = test_ds[i]
    if pred_test[i] == 1:
        image[0:32, :, 0] = 0.9  # 1 entspricht 255
    plt.imshow(image)
    plt.title(pred_test[i])
    plt.axis("off")
# show the figure
plt.show()
fpr_keras, tpr_keras, thresholds_keras = roc_curve(test_labels, pred_test, pos_label=1)
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
