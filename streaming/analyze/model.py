#!/usr/bin/env python

##########################################################################################
# Partial credit to:
# Emaad Manzoor
# As some of the code is adapted from:
# https://github.com/sbustreamspot/sbustreamspot-train/blob/master/create_seed_clusters.py
##########################################################################################

import argparse
import numpy as np
import random
import os, sys
from medoids import _k_medoids_spawn_once
from scipy.spatial.distance import pdist, squareform, hamming
from sklearn.metrics import silhouette_score

class Model():
	"""
	Each training graph constructs a model, which may be merged with other models if possible.
	A model contains the following components:
	1. A list of medoids, e.g., [M_a, M_b, M_c]
	2. Means of each cluster correspond to the medoids, e.g., [A_a, A_b, A_c]
	3. Thresholds of each cluster correspond to the medoids, e.g., [T_a, T_b, T_c]
	4. A list of lists of members belong to each cluster, e.g., [[E_a_1, E_a_2, ...], [E_b_1, E_b_2, ...], [E_c_1, E_c_2, ...]]
	5. The evolution of the graph based on cluster indices, e.g., We have a total three clusters, [0, 1, 2, 1, 2, ...]
	"""
	def __init__(self, medoids, means, thresholds, members, evolution):
		self.medoids = medoids
		self.means = means
		self.thresholds = thresholds
		self.members = members
		self.evolution = evolution

	def print_thresholds(self):
		print self.thresholds

	def print_evolution(self):
		print self.evolution


NUM_TRIALS = 20
NUM_STDS = 3.0
SEED = 42
random.seed(SEED)
np.random.seed(SEED)

# Parse arguments from the user who must provide the following information:
# '--train_dir <directory_path>': the path to the directory that contains data files of all training graphs.
parser = argparse.ArgumentParser()
parser.add_argument('--train_dir', help='Absolute path to the directory that contains all training vectors', required=True)
# '--test_dir <directory_path>': the path to the directory that contains data files of all testing graphs.
parser.add_argument('--test_dir', help='Absolute path to the directory that contains all testing vectors', required=True)
args = vars(parser.parse_args())

train_dir_name = args['train_dir']	# The directory absolute path name from the user input of training vectors.
train_files = os.listdir(train_dir_name)	# The training file names within that directory.
# Note that we will read every file within the directory @train_dir_name.
# We do not do error checking here. Therefore, make sure every file in @train_dir_name is valid.

# We do the same for testing files.
test_dir_name = args['test_dir']	# The directory absolute path name from the user input of testing vectors.
test_files = os.listdir(test_dir_name)	# The testing file names within that directory.

# Now we will open every file and read the sketch vectors in the file for modeling.
# We will create a model for each file and then merge the models if necessary.
# @models contains a list of models from each file.
models = []

for model_num, input_train_file in enumerate(train_files):
	with open(os.path.join(train_dir_name, input_train_file), 'r') as f:
		sketches = []	# The sketch on row i is the ith stage of the changing graph.

		# We read all the sketches in the file and save it in memory in @sketches
		for line in f:
			sketch_vector = map(long, line.strip().split(" "))
			sketches.append(sketch_vector)

		sketches = np.array(sketches)
		# @dists now contains pairwise Hamming distance (using @pdist) between any two sketches in @sketches.
		# @squareform function makes it a matrix for easy indexing and accessing.
		dists = squareform(pdist(sketches, metric='hamming'))
		# We define a @distance function to use in @_k_medoids_spawn_once.
		def distance(x, y):
			return dists[x][y]

		# Now we use mean Silhouette Coefficient to determine the best number of clusters.
		# In our context, a cluster represents a broader "stage" of the progressing, dynamic graph.
		# Clusters show the progress of the changing graph, and all clusters represents one changing graph.
		best_num_clusters = -1	# The best number of clusters. We favor larger numbers of clusters.
		# The best Silhouette Coefficient value is 1 and the worst value is -1. 
		# Values near 0 indicate overlapping clusters. 
		# Negative values generally indicate that a sample has been assigned to the wrong cluster, as a different cluster is more similar.
		best_silhouette_coef = -1
		best_cluster_labels = None	# A vector contains labels for each sketch.
		best_medoids = None	# A vector contains all medoids of clusters and their members (see @Medoid class in @medoids.py).

		for num_clusters in range(2, sketches.shape[0]):	# At least 2 cluster and at most every sketch belongs to a different cluster.
			for trial in range(NUM_TRIALS):	# We run many trials for a given number of clusters for best performance.
				# We use @_k_medoids_spawn_once from @medoids.py for computation.
				_, medoids = _k_medoids_spawn_once(points=range(sketches.shape[0]), k=num_clusters, distance=distance, max_iterations=1000, verbose=False)
				# Now we assign each sketch its cluster number based on the result of the previous computation.
				cluster_labels = [-1] * sketches.shape[0]
				real_cluster_num = len(medoids)	# @num_cluster represents the maximum possible cluster. The actually number of cluster may be smaller.
				for medoid_idx, medoid in enumerate(medoids):
					elements = medoid.elements	# @elements contains all sketch indices (in @sketches based on its row position i) that beling to this medoid's cluster.
					for element in elements:
						cluster_labels[element] = medoid_idx
				cluster_labels = np.array(cluster_labels)

				# TODO: The following should not happen.
				#######################################
				set_labels = set(cluster_labels)
				if (len(set_labels) == 1):
					continue
				#######################################

				# Once we know each sketch belongs to which cluster, we can calculate the Silhouette Coefficient
				silhouette_coef = silhouette_score(sketches, cluster_labels, metric='hamming')

				# Now we decide if this run is the best value seen so far.
				if silhouette_coef > best_silhouette_coef or (silhouette_coef == best_silhouette_coef and real_cluster_num > best_num_clusters):	# We favor larger cluster number.
					best_silhouette_coef = silhouette_coef
					best_num_clusters = real_cluster_num
					best_cluster_labels = cluster_labels
					best_medoids = medoids

		# Now that we have determined the best medoids, we calculate some statistics for modeling.
		# @cluster_means contains a mean for each cluster
		cluster_means = [-1] * best_num_clusters
		# @cluster_thresholds contains a threshold for each cluster.
		# For each cluster, we calulate the threshold based on the mean distances of each member of the cluster from the center, and standard deviations.
		cluster_thresholds = [-1] * best_num_clusters
		# @cluster_medoids contains the sketch vector of each cluster medoid (not just its index in @sketches)
		cluster_medoids = [[]] * best_num_clusters
		# @cluster_members contains the index of each member that belongs to the corresponding medoid.
		cluster_members = [[]] * best_num_clusters
		# @cluster_center contains the index of the medoid of each cluster.
		cluster_center = [-1] * best_num_clusters
		for cluster_idx in range(best_num_clusters):
			cluster_center[cluster_idx] = best_medoids[cluster_idx].kernel	# @kernel is the index of the sketch that is considered the centroid.
			cluster_medoids[cluster_idx] = sketches[cluster_center[cluster_idx]]
			cluster_sketches = best_medoids[cluster_idx].elements	# @elements is a list that contains the indices of all the member sketches in the cluster.
			# @cluster_dists contains all distances between the kernel and each element in @elements
			cluster_members[cluster_idx] = cluster_sketches
			
			cluster_dists = [dists[cluster_center[cluster_idx]][skt] for skt in cluster_sketches if skt != cluster_center[cluster_idx]]
			# Now we can calculate the threshold based on @mean_dist and @std_dist.
			if len(cluster_dists) == 0: # This cluster has only one member.
				meam_dist = 0.0
				std_dist = 0.0
			else:
				mean_dist = np.mean(cluster_dists)
				std_dist = np.std(cluster_dists)
			cluster_means[cluster_idx] = mean_dist
			cluster_thresholds[cluster_idx] = mean_dist + NUM_STDS * std_dist

		# The last step of generating a model from the training graph is to compute the evolution of the graph based on its members and the cluster index to which they belong.
		evolution = []
		prev = -1 	# Check what cluster index a previous sketch is in.
		for elem_idx in range(sketches.shape[0]):	# We go through every sketch to summarize the evolution.
			for cluster_idx in range(best_num_clusters):
				if elem_idx in cluster_members[cluster_idx] or elem_idx == cluster_center[cluster_idx]:
					# We find what cluster index the @elem_idx sketch belongs to.
					current = cluster_idx
					# If @current is equal to @prev, then we will not record it in evolution, since the evolving graph stays in the same cluster.
					if current == prev:
						break	# We simply move on to the next @elem_idx.
					else:
						# Otherwise, we record @current in the @evolution.
						prev = current
						evolution.append(current)

		# Now that we have @evolution, we have all the information we need for our model. We create the model and save it in @models.
		new_model = Model(cluster_medoids, cluster_means, cluster_thresholds, cluster_members, evolution)
		
		print "Model " + str(model_num) + " is done!"
		new_model.print_thresholds()
		new_model.print_evolution()
		
		models.append(new_model)

	# We are done with this training file. Close the file and proceed to the next file.
	f.close()

# TODO: We can merge similar models in @models here.

# Testing code starts here.
for input_test_file in test_files:
	with open(os.path.join(test_dir_name, input_test_file), 'r') as f:
		sketches = []	# The sketch on row i is the ith stage of the changing graph.

		# We read all the sketches in the file and save it in memory in @sketches
		for line in f:
			sketch_vector = map(long, line.strip().split(" "))
			sketches.append(sketch_vector)

		sketches = np.array(sketches)

		abnormal = True # Flag signalling whether the test graph is abnormal.
		check_next_model = False	# Flag signalling whether we should proceed to check with the next model because the current one does not fit.
		# We now fit the sketch vectors in @sketches to each model in @models. 
		# As long as the test graph could fit into one of the models, we will set the @abnormal flag to False.
		# If it could not fit into any of the models, the @abnormal flag remains True and we will signal the user.
		for model in models:
			current_evolution_idx = 0 
			current_cluster_idx = model.evolution[current_evolution_idx]
			current_medoid = model.medoids[current_cluster_idx]	# Get the medoid of the current cluster.
			current_threshold = model.thresholds[current_cluster_idx]	# Get the threshold of the current cluster.
			for sketch in sketches:
				distance_from_medoid = hamming(sketch, current_medoid)	# Compute the hamming distance between the current medoid and the current test vector.
				if distance_from_medoid > current_threshold:
					# We check maybe the evolution has evolved to the next cluster if it exsits.
					if current_evolution_idx < len(model.evolution):	# If there is actually a next cluster in evolution.
						current_evolution_idx = current_evolution_idx + 1 # Let's move on to the next cluster and see if it fits.
						current_cluster_idx = model.evolution[current_evolution_idx]
						current_medoid = model.medoids[current_cluster_idx]
						current_threshold = model.thresholds[current_cluster_idx]
						distance_from_medoid = hamming(sketch, current_medoid)
						if distance_from_medoid > current_threshold:	# if it still does not fit, we consider it abnormal
							check_next_model = True	# So we know this graph does not fit into this model, but it can probably fit into a different model.
							break
						# Else we go check the next sketch in @sketches
					else:	# If there is not a next cluster in evolution
						check_next_model = True	# We consider it abnormal in this model and check next model.
						break	# TODO: we have not yet coded recurrent modelling, which could happen.
			if not check_next_model:
				abnormal = False	# If we don't need to check with the next model, we know this test graph fits in this model, so we are done.
				break
	if not abnormal:	# We have decided that the test graph is not abnormal
		print "This test graph: " + input_test_file + " fits into some model."
	else:
		print "We have tested all the models but " + input_test_file + " does not fit into any model."






























