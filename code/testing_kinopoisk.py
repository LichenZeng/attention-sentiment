# coding: utf-8
import logging
logging.basicConfig(filename='kinopoisk_test.log', level=logging.INFO, format='%(message)s')


# In[1]:
import sys
import numpy as np
import pandas as pd
import cPickle
import multiprocessing



# ### Reading tweets

# In[2]:

review_train = pd.read_csv('../data/kinopoisk_train.csv', encoding='utf-8')

# In[3]:

review_train.head()

# In[4]:

texts, labels = review_train.text.values, review_train.label.values

# ### Reading vocabulary and embeddings

# In[5]:

word2id, embeddings = cPickle.load(open('../data/w2v/vectors_l.pkl', 'rb'))

# word2id[u'</s>'] = embeddings.shape[0]
# embeddings = np.concatenate((embeddings, np.zeros((1, embeddings.shape[1]))))
# In[6]:

vocabulary = word2id.keys()
eos_id = word2id[u'</s>']

# ### Lemmatizing and replacing words with ids

# In[7]:

from nltk.tokenize import RegexpTokenizer
import pymorphy2
logging.getLogger("pymorphy2").setLevel(logging.WARNING)

tokenizer = RegexpTokenizer(u'[а-яА-Яa-zA-Z]+')
morph = pymorphy2.MorphAnalyzer()


def text2seq(text):
    tokens_norm = [morph.parse(w)[0].normal_form for w in tokenizer.tokenize(text)]
    return [word2id[w] for w in tokens_norm if w in vocabulary] + [eos_id]


# sample = texts[49]
#
# print sample
# print u' '.join(tokenizer.tokenize(sample))
# print u' '.join([morph.parse(w)[0].normal_form for w in tokenizer.tokenize(sample)])
# print text2seq(sample)


X = cPickle.load(open('../data/X_kinopoisk_train.pkl', 'rb'))

# Distribution of sequences' lengths

# In[9]:

# plt.hist(map(len, X), bins=length_max);


# Drop samples with the length > 150

# In[10]:

length_max = 1024
y = review_train.label.values
y = y[np.array(map(len, X)) < length_max]
X = [x for x in X if len(x) < length_max]

# ### Zero padding

# In[11]:

X = [x + [eos_id] * (length_max - len(x)) for x in X]

# ### Examples

# In[12]:

# for x in X[:3]:
#     print x
#

# ### Split into train and validation sets

# In[13]:

X = np.array(X)


# In[14]:

def cls2probs(cls):
    if cls == -1:
        return [1.,0.,0.]
    elif cls == 0:
        return [0.,1.,0.]
    else:
        return [0.,0.,1.]
y = np.array([cls2probs(cls) for cls in y])

# In[15]:

from sklearn.model_selection import train_test_split

TEST_SIZE = 0.1

X_tr, X_val, y_tr, y_val = train_test_split(X, y, test_size=TEST_SIZE, random_state=40)

# To use if y is one-dimensional array
from collections import Counter

# print Counter(y_tr)
# print Counter(y_val)
# In[16]:

# print "Train class frequencies:\t", [col.nonzero()[0].shape[0] for col in y_tr.transpose()]
# print "Validation class frequencies:\t", [col.nonzero()[0].shape[0] for col in y_val.transpose()]
# print "Constant classifier's validation accuracy:\t", [col.nonzero()[0].shape[0] for col in y_val.transpose()][1] * 1. / y_val.shape[0]


# ### Resampling
# from imblearn.under_sampling import RandomUnderSampler
# rus = RandomUnderSampler()
# _y = np.argmax(y_tr, 1) - 1
# X_resampled, y_resampled = rus.fit_sample(X_tr, _y)
# y_resampled = np.array([cls2probs(cls) for cls in y_resampled])

# neutral_indices = np.random.choice(np.nonzero(y_tr[:,1])[0], np.nonzero(y_tr[:,0])[0].shape[0], replace=False)
# negative_indices = np.nonzero(y_tr[:,0])[0]
# positive_indices = np.nonzero(y_tr[:,2])[0]
#
# X_resampled = X_tr[np.concatenate([negative_indices, neutral_indices, positive_indices])]
# y_resampled = y_tr[np.concatenate([negative_indices, neutral_indices, positive_indices])]
# # Network learning

# In[17]:

import tensorflow as tf
logging.getLogger("tensorflow").setLevel(logging.WARNING)
from tensorflow.contrib.rnn import GRUCell
from tensorflow.python.ops.rnn import bidirectional_dynamic_rnn as bi_rnn
from tensorflow.contrib.layers import fully_connected

from utils import *

# In[18]:

from sklearn.metrics import f1_score

f_macro = lambda y1, y2: f1_score(y1, y2, average="macro")
f_micro = lambda y1, y2: f1_score(y1, y2, average="micro")

# y_pred_major = np.zeros(y_val.shape)
# y_pred_major[:,1] = 1.
# print "Constant classifier's macro-averaged F-score on validation set:", f_macro(y_val, y_pred_major)
# print "Constant classifier's micro-averaged F-score on validation set:", f_micro(y_val, y_pred_major)


# ### Bi-RNN

# In[120]:

# HIDDEN_SIZE = 300
# ATTENTION_SIZE = 150
nn_type = sys.argv[1]
num_layers = int(sys.argv[2])
HIDDEN_SIZE = int(sys.argv[3])
ATTENTION_SIZE = int(sys.argv[4])
print "Hidden size:", HIDDEN_SIZE
BATCH_SIZE = 256
EPOCHS = int(sys.argv[5])
LEARNING_RATE = float(sys.argv[6])
DROPOUT = float(sys.argv[7])


EMBED_DIM = 300
NUM_CLASSES = 3

tf.reset_default_graph()

batch_ph = tf.placeholder(tf.int32, [None, None])
target_ph = tf.placeholder(tf.float32, [None, NUM_CLASSES])
seq_len_ph = tf.placeholder(tf.int32, [None])
keep_prob_ph = tf.placeholder(tf.float32)

embeddings_ph = tf.placeholder(tf.float32, [len(vocabulary), EMBED_DIM])
embeddings_var = tf.Variable(tf.constant(0., shape=[len(vocabulary), EMBED_DIM]), trainable=False)
init_embeddings = embeddings_var.assign(embeddings_ph)
batch_embedded = tf.nn.embedding_lookup(embeddings_var, batch_ph)

if nn_type == "cnn":
    batch_embedded_expanded = tf.expand_dims(batch_embedded, -1)
    filter_sizes = [3, 4]
    num_filters = 300
    sequence_length = length_max
    # Create a convolution + maxpool layer for each filter size
    pooled_outputs = []
    for i, filter_size in enumerate(filter_sizes):
        # Convolution Layer
        filter_shape = [filter_size, EMBED_DIM, 1, num_filters]
        W = tf.Variable(tf.truncated_normal(filter_shape, stddev=0.1))
        b = tf.Variable(tf.constant(0.1, shape=[num_filters]))
        conv = tf.nn.conv2d(
            batch_embedded_expanded,
            W,
            strides=[1, 1, 1, 1],
            padding="VALID")
        # Apply nonlinearity
        h = tf.nn.relu(tf.nn.bias_add(conv, b), name="relu")
        # Maxpooling over the outputs
        pooled = tf.nn.max_pool(
            h,
            ksize=[1, sequence_length - filter_size + 1, 1, 1],
            strides=[1, 1, 1, 1],
            padding='VALID')
        pooled_outputs.append(pooled)

    # Combine all the pooled features
    num_filters_total = num_filters * len(filter_sizes)
    h_pool = tf.concat(pooled_outputs, 3)
    output = tf.reshape(h_pool, [-1, num_filters_total])
else:
    # Bi-RNN layers
    outputs, _ = bi_rnn(GRUCell(HIDDEN_SIZE), GRUCell(HIDDEN_SIZE),
                        inputs=batch_embedded, sequence_length=seq_len_ph, dtype=tf.float32, scope="bi_rnn1")
    outputs = tf.concat(outputs, 2)
    if num_layers == 2:
        outputs,_ = bi_rnn(GRUCell(HIDDEN_SIZE), GRUCell(HIDDEN_SIZE),
                                 inputs=outputs,sequence_length=seq_len_ph, dtype=tf.float32, scope="bi_rnn2")
        outputs = tf.concat(outputs, 2)

    if nn_type == "rnn":
        # Last output of Bi-RNN
        output = outputs[:, 0, :]
    else:
        SEQ_LENGTH = length_max
        # Attention mechanism
        W_omega = tf.Variable(tf.random_normal([2 * HIDDEN_SIZE, ATTENTION_SIZE], stddev=0.1))
        b_omega = tf.Variable(tf.random_normal([1, ATTENTION_SIZE], stddev=0.1))
        u_omega = tf.Variable(tf.random_normal([ATTENTION_SIZE, 1], stddev=0.1))

        v = tf.nn.relu(tf.matmul(tf.reshape(outputs, [-1, 2 * HIDDEN_SIZE]), W_omega) + b_omega)
        vu = tf.matmul(v, u_omega)
        exps = tf.reshape(tf.exp(vu), [-1, SEQ_LENGTH])
        alphas = exps / tf.reshape(tf.reduce_sum(exps, 1), [-1, 1])

        # Output of Bi-RNN reduced with attention vector
        output = tf.reduce_sum(outputs * tf.reshape(alphas, [-1, SEQ_LENGTH, 1]), 1)


# Dropout
drop = tf.nn.dropout(output, keep_prob_ph)

# Fully connected layer
W = tf.Variable(tf.truncated_normal([HIDDEN_SIZE * 2, NUM_CLASSES], stddev=0.1), name="W")
b = tf.Variable(tf.constant(0., shape=[NUM_CLASSES]), name="b")
y_hat = tf.nn.xw_plus_b(drop, W, b, name="scores")

# In[121]:

# Adam parameters
EPSILON = 1e-5
BETA1 = 0.9
BETA2 = 0.9
# L2 regularization coefficient
BETA = 0

cross_entropy = tf.reduce_mean(tf.nn.softmax_cross_entropy_with_logits(logits=y_hat, labels=target_ph),
                               name="cross_entropy")
l2_loss = tf.nn.l2_loss(W, name="l2_loss")
loss = cross_entropy + l2_loss * BETA
optimizer = tf.train.AdamOptimizer(learning_rate=LEARNING_RATE, beta1=BETA1, beta2=BETA2,
                                   epsilon=EPSILON).minimize(loss)
# optimizer = tf.train.MomentumOptimizer(learning_rate=1e-1, momentum=0.1).minimize(loss)
accuracy = tf.reduce_mean(tf.cast(tf.equal(tf.argmax(target_ph, 1), tf.argmax(y_hat, 1)), tf.float32))

# In[122]:

train_batch_generator = batch_generator(X_tr, y_tr, BATCH_SIZE)

loss_tr_l = []
loss_val_l = []
ce_tr_l = []  # Cross-entropy
ce_val_l = []
acc_tr_l = []  # Accuracy
acc_val_l = []
f_macro_tr_l = []
f_macro_val_l = []
f_fair_tr_l = []
f_fair_val_l = []
max_val_f = 0.

with tf.Session() as sess:
    saver = tf.train.Saver()
    sess.run(tf.global_variables_initializer())
    sess.run(init_embeddings, feed_dict={embeddings_ph: embeddings})
    print "Start learning..." + sys.argv[1]
    for epoch in range(EPOCHS):
        for i in range(int(X_tr.shape[0] / BATCH_SIZE)):
            x_batch, y_batch = train_batch_generator.next()
            seq_len_tr = np.array([list(x).index(eos_id) + 1 for x in x_batch])
            sess.run(optimizer, feed_dict={batch_ph: x_batch, target_ph: y_batch,
                                           seq_len_ph: seq_len_tr, keep_prob_ph: DROPOUT})

        y_pred_tr, ce_tr, loss_tr, acc_tr = sess.run([y_hat, cross_entropy, loss, accuracy],
                                                     feed_dict={batch_ph: x_batch, target_ph: y_batch,
                                                                seq_len_ph: seq_len_tr, keep_prob_ph: 1.0})

        y_pred_val, ce_val, loss_val, acc_val = [], 0, 0, 0
        num_val_batches = X_val.shape[0] / BATCH_SIZE
        for i in range(num_val_batches):
            x_batch_val, y_batch_val = X_val[i * BATCH_SIZE: (i + 1) * BATCH_SIZE], y_val[i * BATCH_SIZE: (
                                                                                                              i + 1) * BATCH_SIZE]
            seq_len_val = np.array([list(x).index(eos_id) + 1 for x in x_batch_val])
            y_pred_val_, ce_val_, loss_val_, acc_val_ = sess.run([y_hat, cross_entropy, loss, accuracy],
                                                                 feed_dict={batch_ph: x_batch_val,
                                                                            target_ph: y_batch_val,
                                                                            seq_len_ph: seq_len_val,
                                                                            keep_prob_ph: 1.0})
            y_pred_val += list(y_pred_val_)
            ce_val += ce_val_
            loss_val += loss_val_
            acc_val += acc_val_

        y_pred_val = np.array(y_pred_val)
        ce_val /= num_val_batches
        loss_val /= num_val_batches
        acc_val /= num_val_batches

        y_pred_tr = np.array([cls2probs(cls) for cls in np.argmax(y_pred_tr, 1) - 1])
        y_pred_val = np.array([cls2probs(cls) for cls in np.argmax(y_pred_val, 1) - 1])
        f_macro_tr, f_micro_tr = f_macro(y_batch, y_pred_tr), f_micro(y_batch, y_pred_tr)
        f_macro_val, f_micro_val = f_macro(y_val[:num_val_batches * BATCH_SIZE], y_pred_val), f_micro(
            y_val[:num_val_batches * BATCH_SIZE], y_pred_val)

        loss_tr_l.append(loss_tr)
        loss_val_l.append(loss_val)
        ce_tr_l.append(ce_tr)
        ce_val_l.append(ce_val)
        acc_tr_l.append(acc_tr)
        acc_val_l.append(acc_val)
        f_macro_tr_l.append(f_macro_tr)
        f_macro_val_l.append(f_macro_val)

        print "epoch: {}".format(epoch)
        print "\t Train loss: {:.3f}\t ce: {:.3f}\t acc: {:.3f}\t f_macro: {:.3f}".format(
            loss_tr, ce_tr, acc_tr, f_macro_tr)
        print "\t Valid loss: {:.3f}\t ce: {:.3f}\t acc: {:.3f}\t f_macro: {:.3f}".format(
            loss_val, ce_val, acc_val, f_macro_val)

        if f_macro_val > max_val_f:
            max_val_f = f_macro_val
            saver.save(sess, 'model')

    results = [max(acc_val_l), max(f_macro_val_l)]
    # saver.save(sess, 'model')

# In[123]:

print "Val. results:", results

# # Testing

# In[ ]:

review_test = pd.read_csv('../data/kinopoisk_test.csv', sep=',', encoding='utf-8')
texts_test, labels_test = review_test.text.values, review_test.label.values

# %%time
# pool = multiprocessing.Pool()
# X_test = pool.map(text2seq, texts_test)
# cPickle.dump(X_test, open('../data/X_kinopoisk_test.pkl', 'wb'))

# In[ ]:

X_test = cPickle.load(open('../data/X_kinopoisk_test.pkl', 'rb'))

# In[ ]:

X_test = [x[:length_max - 1] for x in X_test]
X_test = [x + [eos_id] * (length_max - len(x)) for x in X_test]
X_test = np.array(X_test)
y_test = np.array([cls2probs(cls) for cls in labels_test])

#
# # In[ ]:
#
# X_test.shape, y_test.shape


# In[ ]:

with tf.Session() as sess:
    new_saver = tf.train.import_meta_graph('model.meta')
    new_saver.restore(sess, tf.train.latest_checkpoint('./'))

    y_pred_test, ce_test, loss_test, acc_test = [], 0, 0, 0
    num_test_batches = X_test.shape[0] / BATCH_SIZE
    for i in range(num_test_batches):
        x_batch_test, y_batch_test = X_test[i * BATCH_SIZE: (i + 1) * BATCH_SIZE], y_test[
                                                                                   i * BATCH_SIZE: (i + 1) * BATCH_SIZE]
        seq_len_test = np.array([list(x).index(eos_id) + 1 for x in x_batch_test])
        y_pred_test_, ce_test_, loss_test_, acc_test_ = sess.run([y_hat, cross_entropy, loss, accuracy],
                                                                 feed_dict={batch_ph: x_batch_test,
                                                                            target_ph: y_batch_test,
                                                                            seq_len_ph: seq_len_test,
                                                                            keep_prob_ph: 1.0})
        y_pred_test += list(y_pred_test_)
        ce_test += ce_test_
        loss_test += loss_test_
        acc_test += acc_test_


    # y_pred_val, ce_val, loss_val, acc_val = [], 0, 0, 0
    # num_val_batches = X_val.shape[0] / BATCH_SIZE
    # for i in range(num_val_batches):
    #     x_batch_val, y_batch_val = X_val[i * BATCH_SIZE: (i + 1) * BATCH_SIZE], y_val[i * BATCH_SIZE: (i + 1) * BATCH_SIZE]
    #     seq_len_val = np.array([list(x).index(eos_id) + 1 for x in x_batch_val])
    #     y_pred_val_, ce_val_, loss_val_, acc_val_ = sess.run([y_hat, cross_entropy, loss, accuracy],
    #                                                          feed_dict={batch_ph: x_batch_val,
    #                                                                     target_ph: y_batch_val,
    #                                                                     seq_len_ph: seq_len_val,
    #                                                                     keep_prob_ph: 1.0})
    #     y_pred_val += list(y_pred_val_)
    #     ce_val += ce_val_
    #     loss_val += loss_val_
    #     acc_val += acc_val_
    #
    # y_pred_val = np.array(y_pred_val)
    # ce_val /= num_val_batches
    # loss_val /= num_val_batches
    # acc_val /= num_val_batches
    #
    # y_pred_val = np.array([cls2probs(cls) for cls in np.argmax(y_pred_val, 1) - 1])
    # f_macro_val, f_micro_val = f_macro(y_val[:num_val_batches * BATCH_SIZE], y_pred_val), f_micro(
    #     y_val[:num_val_batches * BATCH_SIZE], y_pred_val)

    y_pred_test = np.array(y_pred_test)
    ce_test /= num_test_batches
    loss_test /= num_test_batches
    acc_test /= num_test_batches

# In[ ]:

y_pred_test = np.array([cls2probs(cls) for cls in np.argmax(y_pred_test, 1) - 1])
f_macro_test = f_macro(y_test[:num_test_batches * BATCH_SIZE], y_pred_test)
print "Test results:", acc_test, f_macro_test
# print "Val results:", acc_val, f_macro_val


logging.info("{}, hid_size {}, att_size {}, dropout {}, lr {}".format(nn_type, HIDDEN_SIZE, ATTENTION_SIZE, DROPOUT, LEARNING_RATE))
logging.info("val\t{} {}".format(results[0], results[1]))
logging.info("test\t{} {}".format(acc_test, f_macro_test))
logging.info("\n")
