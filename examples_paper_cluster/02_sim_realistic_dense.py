#!/usr/bin/env python
# coding: utf-8

"""
Part 3: Generate sensor level recordings and compute optimal parameters
=======================================================================

"""
import os.path as op
import os
import numpy as np
import math
import sys
import time
import datetime
from scipy import optimize, signal
from mne import (read_forward_solution, convert_forward_solution,
                 pick_types_forward)
import functions_code as myf
target = '.'
noct = '6'
t_init = time.time()

###############################################################################
# load data

# data path
file_fwd = op.join(target, 'data', 'oct'+noct+'_fwd.fif')

# load fwd
fwd = read_forward_solution(file_fwd, verbose=False)
fwd = convert_forward_solution(
    fwd, surf_ori=True, force_fixed=True, use_cps=True, verbose=False)
fwd = pick_types_forward(fwd, meg='mag', eeg=False, ref_meg=False)

# leadfield matrix
G = fwd['sol']['data']
G = 10**5*G  # rescale to avoid small numbers
GGt = G.dot(G.T)


sys.stdout.flush()

# dipols position
dip_pos = fwd['source_rr']

# dipols orientations
dip_or = fwd['source_nn']

# load cortico-cortical distance matrix
cortico_dist_file = op.join(target, 'data', 'cortico_dist_oct'+noct+'.npy')
cortico_dist = np.load(cortico_dist_file)

###############################################################################
# Load seeds time courses and locations
seed_tc_loc = np.load('./run_data/seed_tc_loc.npy', allow_pickle='TRUE').item()

###############################################################################
# define features of the simulation

features = seed_tc_loc['features']
seed_tcs = seed_tc_loc['seed_tcs']
seed_locs = seed_tc_loc['seed_locs']
N_mod = int(sys.argv[1])  # Number of simulated AR models (with connections)
N_act = features['N_act']
N_loc = int(sys.argv[2])  # Number of different connected pairs of locations
T = features['T']
fs = features['fs']
fmin = features['fmin']
fmax = features['fmax']
# radius of the patch (maximum distance from the seed in meters)
patch_radii = np.sqrt((np.array([2, 4, 8])*10**(-4))/math.pi)
coh_levels = np.array([1, 0.5, 0.2])  # intra coherence levels
bg_noise_levels = np.array([0.1, 0.5, 0.9])  # intensity of background noise
N_snr = int(4)  # Number of snr levels
SNR_val = np.linspace(-20, 5, N_snr)  # SNR values
M = G.shape[0]  # Number of sensor
N_dense = G.shape[1]  # Number of sources in the dense source space

# store newly defined features
features['patch_radii'] = patch_radii
features['coh_levels'] = coh_levels
features['bg_noise_levels'] = bg_noise_levels
features['SNR_val'] = SNR_val


###############################################################################
# simulate sensor level data and compute optimal parameters

job_run = int(sys.argv[3]) - 1
i_mod = job_run % N_mod
i_loc = job_run//N_mod
print('i_mod='+str(i_mod))
print('i_loc='+str(i_loc))
sys.stdout.flush()
seed_loc = seed_locs[i_loc, :]
seed_tc = seed_tcs[:, :, i_mod]
lambdas = np.logspace(-5, 1, num=15)

# initialize dictionary to store the parameters
parameters = {'tc': np.zeros((len(patch_radii), len(coh_levels),
                              len(bg_noise_levels), N_snr, 4)),
              'tc_AUC': np.zeros((len(patch_radii), len(coh_levels),
                                  len(bg_noise_levels), N_snr, 2, len(lambdas))),
              'conn': np.zeros((len(patch_radii), len(coh_levels),
                                len(bg_noise_levels), N_snr, 4, len(lambdas))),
              'TPF_conn': np.zeros((len(patch_radii), len(coh_levels),
                                    len(bg_noise_levels), N_snr, len(lambdas),
                                    4, 20)),
              'FPF_conn': np.zeros((len(patch_radii), len(coh_levels),
                                    len(bg_noise_levels), N_snr, len(lambdas),
                                    4, 20)),
              'sigma_noise': np.zeros((len(patch_radii), len(coh_levels),
                                       len(bg_noise_levels), N_snr))}

# initialize matrix to store spectral complecxity levels
spectal_complexity_Y = np.zeros(
    (len(patch_radii), len(coh_levels), len(bg_noise_levels), N_snr))

nperseg = 256
nfft = nperseg
P = 5

for r in patch_radii:
    i_r = np.where(patch_radii == r)[0][0]
    # define patches given the seeds and the radius
    print('generating patches')
    sys.stdout.flush()
    p1_locs, p2_locs = myf.gen_patches_sources(cortico_dist, r, seed_loc)

    for c in coh_levels:
        i_c = np.where(coh_levels == c)[0][0]

        # generate coherent patches
        print('generating patch tcs')
        sys.stdout.flush()
        tic = time.time()
        p1_tcs, p2_tcs = myf.gen_coherent_patches(
            seed_tc, p1_locs, p2_locs, c, i_c, nperseg, nfft, fs, fmin, fmax)
        toc = time.time()
        print('time for generating coherent patches:'+str(toc-tic))
        sys.stdout.flush()

        # generate background activity
        print('generating background tcs')
        sys.stdout.flush()
        tic = time.time()
        bg_locs = np.setdiff1d(
            np.arange(N_dense), np.concatenate((p1_locs, p2_locs)))
        bg_tcs_general = myf.gen_background_tcs(P, len(bg_locs), T)
        toc = time.time()
        print('time for generating background tcs:'+str(toc-tic))
        sys.stdout.flush()

        # define the norm of patches and background activity to define the snr
        # between patches and bg
        patches_norm = np.linalg.norm(np.concatenate(
            (p1_tcs, p2_tcs), axis=0), ord='fro')**2
        bg_norm_general = np.linalg.norm(bg_tcs_general, ord='fro')**2

        for Gamma in bg_noise_levels:
            i_gamma = np.where(bg_noise_levels == Gamma)[0][0]

            # scale bg activity to the desired level of Gamma
            bg_tcs = bg_tcs_general * \
                np.sqrt((patches_norm/bg_norm_general)*Gamma)

            # define brain activity
            X = np.zeros((N_dense, T))
            X[bg_locs, :] = bg_tcs
            X[p1_locs, :] = p1_tcs
            X[p2_locs, :] = p2_tcs
            for Alpha in SNR_val:
                i_snr = np.where(SNR_val == Alpha)[0][0]

                # generate sensor level noise
                N_tilde = np.random.randn(M, T)
                Sigma = np.sqrt(np.linalg.norm(G.dot(X), ord='fro')**2 /
                                (10**(Alpha/10)*np.linalg.norm(N_tilde, ord='fro')**2))
                N = Sigma*N_tilde
                parameters['sigma_noise'][i_r, i_c, i_gamma, i_snr] = Sigma

                # define sensor data
                Y = G.dot(X)+N

                spectal_complexity_Y[i_r, i_c, i_gamma, i_snr] = myf.spectral_complexity(
                    Y, fs, nperseg, fmin, fmax)

                # define the matrix of positives and negatives (positives=1,
                # negtives=0) for neural activity
                PN_matrix_tc = np.zeros((N_dense, ), dtype=int)
                PN_matrix_tc[p1_locs] = np.ones((len(p1_locs), ), dtype=int)
                PN_matrix_tc[p2_locs] = np.ones((len(p2_locs), ), dtype=int)

                # define the matrix of positives and negatives (positives=1,
                # negtives=0) for connectivity
                PN_matrix_conn = np.zeros((len(p1_locs), N_dense), dtype=int)
                PN_matrix_conn[:, p2_locs] = np.ones(
                    (len(p1_locs), len(p2_locs)), dtype=int)
                PN_matrix_conn = np.delete(PN_matrix_conn, p1_locs, axis=-1)

                # COMPUTE REGULARIZATION PARAMETERS

                tic = time.time()
                sys.stdout.flush()
                b, a = signal.butter(3, np.array(
                    [8, 12]), btype='bandpass', analog=False, output='ba', fs=fs)
                X_filt = signal.filtfilt(b, a, X, axis=- 1, padtype='odd',
                                         padlen=None, method='pad', irlen=None)
                Y_filt = signal.filtfilt(b, a, Y, axis=- 1, padtype='odd',
                                         padlen=None, method='pad', irlen=None)
                input_lamX = np.linalg.norm(
                    N, ord='fro')**2/np.linalg.norm(G.dot(X), ord='fro')**2

                print('computing lam X')
                # lambda X
                opt_set = optimize.minimize(myf.err_X, input_lamX, args=(
                    X, Y, G, GGt), method='Nelder-Mead')
                lamX = opt_set['x'][0].copy()

                # lambda X alpha range
                opt_set = optimize.minimize(myf.err_X, input_lamX, args=(
                    X_filt, Y_filt, G, GGt), method='Nelder-Mead')
                lamX_alpha = opt_set['x'][0].copy()

                toc = time.time()
                print('time for computing lamX:'+str(toc-tic))
                sys.stdout.flush()

                # lambda connectivity
                print('computing optimal parameters for connectivity')
                tic = time.time()
                sys.stdout.flush()

                # TPF, dimension: lambdas*conn_meths*thresholds
                TPF_conn = np.zeros((len(lambdas), 4, 20))
                # FPF, dimension: lambdas*conn_meths*thresholds
                FPF_conn = np.zeros((len(lambdas), 4, 20))
                AUC_conn = np.zeros((len(lambdas), 4))
                for i_lam in range(len(lambdas)):
                    AUC_conn[i_lam, :], TPF_conn[i_lam, :, :], FPF_conn[i_lam, :, :], = myf.auc(
                        lambdas[i_lam]*lamX, ['cpsd', 'imcoh', 'ciplv', 'wpli'], G, GGt, Y,
                        p1_locs, p2_locs, fmin, fmax, PN_matrix_conn, fs, nperseg)

                parameters['tc'][i_r, i_c, i_gamma, i_snr, 0] = lamX.copy()
                parameters['tc'][i_r, i_c, i_gamma,
                                 i_snr, 1] = lamX_alpha.copy()
                parameters['conn'][i_r, i_c, i_gamma,
                                   i_snr, 0, :] = AUC_conn[:, 0].copy()
                parameters['conn'][i_r, i_c, i_gamma,
                                   i_snr, 1, :] = AUC_conn[:, 1].copy()
                parameters['conn'][i_r, i_c, i_gamma,
                                   i_snr, 2, :] = AUC_conn[:, 2].copy()
                parameters['conn'][i_r, i_c, i_gamma,
                                   i_snr, 3, :] = AUC_conn[:, 3].copy()
                parameters['TPF_conn'][i_r, i_c, i_gamma,
                                       i_snr, :, :, :] = TPF_conn.copy()
                parameters['FPF_conn'][i_r, i_c, i_gamma,
                                       i_snr, :, :, :] = FPF_conn.copy()

                toc = time.time()
                print(
                    'time for computing optimal parameters for connectivity:'+str(toc-tic))
                print(str(i_r), str(i_c), str(i_gamma), str(i_snr))
                sys.stdout.flush()


###############################################################################
# simulate sensor level data and compute optimal parameters

if not op.isdir('./run_data/'+str(job_run+1)):
    os.makedirs('./run_data/'+str(job_run+1))

np.save('./run_data/'+str(job_run+1)+'/opt_parameters_loc'+str(i_loc) +
        '_mod'+str(i_mod)+'_i_run'+str(job_run+1)+'.npy', parameters)
np.save('./run_data/'+str(job_run+1)+'/spectal_complexity_Y_loc'+str(i_loc) +
        '_mod'+str(i_mod)+'_i_run'+str(job_run+1)+'.npy', spectal_complexity_Y)
if (i_loc == 0 & i_mod == 0):
    np.save('./run_data/tested_parameters.npy', lambdas)
    np.save('./run_data/features.npy', features)

print('total run time: ' + str(datetime.timedelta(seconds=time.time()-t_init)))
