import tensorflow as tf
from models.base_model import BaseModel

FLAGS = tf.app.flags.FLAGS


def linear_layer(name, x, in_size, out_size, is_regularize=False):
	with tf.variable_scope(name):
		loss_l2 = tf.constant(0, dtype=tf.float32)
		w = tf.get_variable('linear_W', [in_size, out_size],
							initializer=tf.truncated_normal_initializer(stddev=0.1))
		b = tf.get_variable('linear_b', [out_size],
							initializer=tf.constant_initializer(0.1))
		o = tf.nn.xw_plus_b(x, w, b)  # batch_size, out_size
		if is_regularize:
			loss_l2 += tf.nn.l2_loss(w) + tf.nn.l2_loss(b)
		return o, loss_l2


def crnn_forward(name, sent_pos, filter_size_list, num_filters1, num_filters2, layer_size, keep_prob_rnn):
	input = tf.expand_dims(sent_pos, axis=-1)
	input_dim = input.shape.as_list()[2]
	filter_size_len = len(filter_size_list)
	conv_outputs = []
	for filter_size in filter_size_list:
		with tf.variable_scope('conv-%s' % filter_size):
			conv_weight = tf.get_variable('W' + str(filter_size),
										  [filter_size, input_dim, 1, num_filters1],
										  initializer=tf.truncated_normal_initializer(stddev=0.1))
			conv_bias = tf.get_variable('b' + str(filter_size),
										[num_filters1],
										initializer=tf.constant_initializer(0.1))
			conv = tf.nn.conv2d(input,
								conv_weight,
								strides=[1, 1, input_dim, 1],
								padding='SAME')
			conv = tf.nn.relu(conv + conv_bias)
			conv_outputs.append(conv)
	convs = tf.concat(conv_outputs, 2)
	with tf.variable_scope('elementwisePooling'):
		pool = tf.nn.max_pool(convs,
							  ksize=[1, 1, filter_size_len, 1],
							  strides=[1, 1, 1, 1],
							  padding='VALID')
	pool = tf.squeeze(pool, axis=2)
	max_len = FLAGS.max_len
	inputs = tf.unstack(pool, num=max_len, axis=1)
	import pdb
	pdb.set_trace()
	with tf.variable_scope('rnn-%s' % filter_size_len):
		lstm_fw_cell = tf.nn.rnn_cell.DropoutWrapper(tf.contrib.rnn.MultiRNNCell(
			[tf.contrib.rnn.LSTMCell(num_units=num_filters2) for _ in range(layer_size)]), keep_prob_rnn)
		lstm_bw_cell = tf.nn.rnn_cell.DropoutWrapper(tf.contrib.rnn.MultiRNNCell(
			[tf.contrib.rnn.LSTMCell(num_units=num_filters2) for _ in range(layer_size)]), keep_prob_rnn)
		outputs, _, _ = tf.contrib.rnn.static_bidirectional_rnn(lstm_fw_cell, lstm_bw_cell, inputs, dtype=tf.float32)

	feature = tf.concat(outputs, 1)
	return feature


class CRNNEPModel(BaseModel):

	def __init__(self, word_embed, data, word_dim,
				 pos_num, pos_dim, num_relations,
				 keep_prob, filter_size, num_filters1,
				 num_filters2, layer_size, keep_prob_rnn, lrn_rate, is_train):
		# input data
		lexical, rid, sentence, pos1, pos2 = data

		# embedding initialization
		w_trainable = True if FLAGS.word_dim == 50 else False
		word_embed = tf.get_variable('word_embed',
									 initializer=word_embed,
									 dtype=tf.float32,
									 trainable=w_trainable)
		pos1_embed = tf.get_variable('pos1_embed', shape=[pos_num, pos_dim])
		pos2_embed = tf.get_variable('pos2_embed', shape=[pos_num, pos_dim])

		filter_size_list = filter_size.split(',')
		# # embedding lookup
		lexical = tf.nn.embedding_lookup(word_embed, lexical)  # batch_size, 6, word_dim
		lexical = tf.reshape(lexical, [-1, 6 * word_dim])
		self.labels = tf.one_hot(rid, num_relations)  # batch_size, num_relations

		sentence = tf.nn.embedding_lookup(word_embed, sentence)  # batch_size, max_len, word_dim
		pos1 = tf.nn.embedding_lookup(pos1_embed, pos1)  # batch_size, max_len, pos_dim
		pos2 = tf.nn.embedding_lookup(pos2_embed, pos2)  # batch_size, max_len, pos_dim
		# cnn model
		sent_pos = tf.concat([sentence, pos1, pos2], axis=2)
		if is_train:
			sent_pos = tf.nn.dropout(sent_pos, keep_prob)

		feature = crnn_forward('crnn_element_wise_pooling', sent_pos, filter_size_list, num_filters1, num_filters2,
							   layer_size, keep_prob_rnn)
		feature_size = feature.shape.as_list()[1]
		self.feature = feature

		if is_train:
			feature = tf.nn.dropout(feature, keep_prob)

		# Map the features to 19 classes
		logits, loss_l2 = linear_layer('linear', feature,
									   feature_size, num_relations,
									   is_regularize=True)

		prediction = tf.nn.softmax(logits)
		prediction = tf.argmax(prediction, axis=1)
		accuracy = tf.equal(prediction, tf.argmax(self.labels, axis=1))
		accuracy = tf.reduce_mean(tf.cast(accuracy, tf.float32))
		loss_ce = tf.reduce_mean(
			tf.nn.softmax_cross_entropy_with_logits(labels=self.labels, logits=logits))
		tf.summary.scalar('loss', loss_ce)
		self.logits = logits
		self.prediction = prediction
		self.accuracy = accuracy
		self.loss = loss_ce + 0.01 * loss_l2

		if not is_train:
			return

		# global_step = tf.train.get_or_create_global_step()
		global_step = tf.Variable(0, trainable=False, name='step', dtype=tf.int32)
		optimizer = tf.train.AdamOptimizer(lrn_rate)

		update_ops = tf.get_collection(tf.GraphKeys.UPDATE_OPS)
		with tf.control_dependencies(update_ops):  # for batch_norm
			self.train_op = optimizer.minimize(self.loss, global_step)
		self.global_step = global_step


def build_train_valid_model(word_embed, train_data, test_data):
	with tf.name_scope("Train"):
		with tf.variable_scope('CRNNModel', reuse=None):
			m_train = CRNNEPModel(word_embed, train_data, FLAGS.word_dim,
								FLAGS.pos_num, FLAGS.pos_dim, FLAGS.num_relations,
								FLAGS.keep_prob, FLAGS.filter_size, FLAGS.num_filters1,
								FLAGS.num_filters2, FLAGS.layer_size, FLAGS.keep_prob_rnn, FLAGS.lrn_rate, is_train=True)
	with tf.name_scope('Valid'):
		with tf.variable_scope('CRNNModel', reuse=True):
			m_valid = CRNNEPModel(word_embed, test_data, FLAGS.word_dim,
								FLAGS.pos_num, FLAGS.pos_dim, FLAGS.num_relations,
								1.0, FLAGS.filter_size, FLAGS.num_filters1,
								FLAGS.num_filters2, FLAGS.layer_size, 1.0, FLAGS.lrn_rate, is_train=False)
	return m_train, m_valid
