import os
import time
import sys
import tensorflow as tf
import numpy as np
from reader import base as base_reader
from models import crnn_model

# tf.set_random_seed(0)
# np.random.seed(0)

flags = tf.app.flags

flags.DEFINE_string("train_file", "data/train.cln",
					"original training file")
flags.DEFINE_string("test_file", "data/test.cln",
					"original test file")

flags.DEFINE_string("vocab_file", "data/vocab.txt",
					"vocab of train and test data")

flags.DEFINE_string("google_embed300_file",
					"data/dep300.npy",
					"google news word embeddding")
flags.DEFINE_string("google_words_file",
					"data/depwords.lst",
					"google words list")
flags.DEFINE_string("trimmed_embed300_file",
					"data/embed300.trim.npy",
					"trimmed google embedding")

flags.DEFINE_string("senna_embed50_file",
					"data/embed50.senna.npy",
					"senna words embeddding")
flags.DEFINE_string("senna_words_file",
					"data/senna_words.lst",
					"senna words list")
flags.DEFINE_string("trimmed_embed50_file",
					"data/embed50.trim.npy",
					"trimmed senna embedding")

flags.DEFINE_string("train_record", "data/train.tfrecord",
					"training file of TFRecord format")
flags.DEFINE_string("test_record", "data/test.tfrecord",
					"Test file of TFRecord format")

flags.DEFINE_string("relations_file", "data/relations.txt", "relations file")
flags.DEFINE_string("results_file", "data/results.txt", "predicted results file")
flags.DEFINE_string("logdir", "saved_models/", "where to save the model")

flags.DEFINE_integer("max_len", 98, "max length of sentences")
flags.DEFINE_integer("num_relations", 19, "number of relations")
flags.DEFINE_integer("word_dim", 50, "word embedding size")
flags.DEFINE_integer("num_epochs", 500, "number of epochs")
flags.DEFINE_integer("batch_size", 100, "batch size")

flags.DEFINE_integer("pos_num", 123, "number of position feature")
flags.DEFINE_integer("pos_dim", 5, "position embedding size")
flags.DEFINE_integer("num_filters1", 75, "cnn number of output unit")
flags.DEFINE_integer("num_filters2", 100, "rnn number of output unit")

flags.DEFINE_integer("layer_size", 2, "number of rnn layer")
flags.DEFINE_string("filter_size", "2,3,4", "conv size")
flags.DEFINE_integer("attention_size", 100, "attention_size")
flags.DEFINE_float("lrn_rate", 1e-3, "learning rate")
flags.DEFINE_float("keep_prob", 0.5, "dropout keep probability")
flags.DEFINE_float("keep_prob_rnn", 0.25, "rnn dropout keep probability")

flags.DEFINE_boolean('test', False, 'set True to test')
flags.DEFINE_boolean('trace', False, 'set True to test')

FLAGS = tf.app.flags.FLAGS


def trace_runtime(sess, m_train):
	'''
	trace runtime bottleneck using timeline api

	navigate to the URL 'chrome://tracing' in a Chrome web browser,
	click the 'Load' button and locate the timeline file.
	'''
	run_metadata = tf.RunMetadata()
	options = tf.RunOptions(trace_level=tf.RunOptions.FULL_TRACE)
	from tensorflow.python.client import timeline
	trace_file = open('timeline.ctf.json', 'w')

	fetches = [m_train.train_op, m_train.loss, m_train.accuracy]
	_, loss, acc = sess.run(fetches,
							options=options,
							run_metadata=run_metadata)

	trace = timeline.Timeline(step_stats=run_metadata.step_stats)
	trace_file.write(trace.generate_chrome_trace_format())
	trace_file.close()


def train(sess, m_train, m_valid):
	n = 1
	best = .0
	best_step = n
	start_time = time.time()
	orig_begin_time = start_time

	fetches = [m_train.train_op, m_train.loss, m_train.accuracy]

	while True:
		try:
			_, loss, acc = sess.run(fetches)

			epoch = n // 80
			if n % 80 == 0:
				now = time.time()
				duration = now - start_time
				start_time = now
				v_acc = sess.run(m_valid.accuracy)
				if best < v_acc:
					best = v_acc
					best_step = n
					m_train.save(sess, best_step)
				print("Epoch %d, loss %.2f, acc %.2f %.4f, time %.2f" %
					  (epoch, loss, acc, v_acc, duration))
				sys.stdout.flush()
			n += 1
		except tf.errors.OutOfRangeError:
			break

	duration = time.time() - orig_begin_time
	duration /= 3600
	print('Done training, best_step: %d, best_acc: %.4f' % (best_step, best))
	print('duration: %.2f hours' % duration)
	sys.stdout.flush()


def test(sess, m_valid):
	m_valid.restore(sess)
	fetches = [m_valid.accuracy, m_valid.prediction]
	accuracy, predictions = sess.run(fetches)
	print('accuracy: %.4f' % accuracy)

	base_reader.write_results(predictions, FLAGS.relations_file, FLAGS.results_file)


def main(_):
	with tf.Graph().as_default():
		train_data, test_data, word_embed = base_reader.inputs()

		m_train, m_valid = crnn_model.build_train_valid_model(word_embed,
															  train_data, test_data)

		m_train.set_saver('crnn-%d-%d' % (FLAGS.num_epochs, FLAGS.word_dim))

		init_op = tf.group(tf.global_variables_initializer(),
						   tf.local_variables_initializer())  # for file queue

		config = tf.ConfigProto()
		# config.gpu_options.per_process_gpu_memory_fraction = 0.9 # 占用GPU90%的显存
		config.gpu_options.allow_growth = True

		# sv finalize the graph
		with tf.Session(config=config) as sess:
			sess.run(init_op)
			print('=' * 80)
			writer = tf.summary.FileWriter("logs/", sess.graph)
			if FLAGS.trace:
				trace_runtime(sess, m_train)
			elif FLAGS.test:
				test(sess, m_valid)
			else:
				train(sess, m_train, m_valid)


if __name__ == '__main__':
	tf.app.run()
