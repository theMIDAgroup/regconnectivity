"""
Main functions
==============

Functions used in files 01_generate_seed_tc.py and 02_sim_realistic_dense.py
"""

#!/usr/bin/env python
# coding: utf-8


import numpy as np
import mne
from scipy import signal
from scipy.fft import fft, ifft

###############################################################################


def select_sources(G, src, N_loc):
    """
    Select N_loc pairs of active sources, given the leadfield (G) and the
    source locations (src), so that the distance between the two sources is
    grater than 4 cm (0.04 m) and the intensity at sensor level is similar
    (i.e. the ratio of the norm of the corresponding leadfield columns is in
    (9/10, 10/9))

    Parameters:
        G: array, shape (N_sensors, N_sources)
            leadfeld matrix
        src: array, shape (N_sources, 3)
            sources locations in the source space
        N_loc: int
            number of pairs of sources

    Returns:
        sample: array, shape (N_loc, 2)
            index of the selected sources in the source space
    """
    sample = np.array([[int(0)]*2]*N_loc)
    for k in range(N_loc):
        ratio = np.inf
        d = 0
        while ratio < 9/10 or ratio > 10/9 or d < 0.04:
            sample[k] = np.random.permutation(G.shape[1])[0:2]
            norm1 = np.linalg.norm(np.transpose(G)[sample[k, 0]])
            norm2 = np.linalg.norm(np.transpose(G)[sample[k, 1]])
            ratio = norm1/norm2
            d = np.linalg.norm(src[sample[k, 0]]-src[sample[k, 1]])
    return sample

###############################################################################


def gen_ar_model(N_act, P, Sigma):
    """
    Generate an MVAR model with directional coupling from source 1 to source 2,
    the third source, if present, is uncorrelated to the the first two

    Parameters:
        N_act: 2, 3
            dimension of the model (i.e. number of time courses to be simulated)
        P: int
            order of the model
        Sigma: float (in (0.1, 1))
            variance of the non zero entries of the model

    Returns:
        model: dictionary
            Dictionary containing:\n
                * the matrices that define the model
                * N_act
                * P
    """

    lambdamax = 10
    I = np.eye(N_act)
    vect = (np.array([int(1)]), np.array([int(0)]))
    index = np.where(I == 1)
    vect = (np.concatenate((vect[0], index[0])),
            np.concatenate((vect[1], index[1])))
    while lambdamax < 0.9 or lambdamax >= 1:
        Arsig = np.array([[], []])
        for k in range(P):
            aloc = np.zeros([N_act, N_act])
            for s in range(vect[0].shape[0]):
                aloc[vect[0][s], vect[1][s]] = np.random.randn(1)[0]*Sigma
            Arsig = np.concatenate((Arsig, aloc), axis=1)
        E = np.eye(N_act*P)
        AA = np.concatenate((Arsig, E[0:-N_act, :]))
        Lambda = np.linalg.eig(AA)[0]
        lambdamax = max(abs(Lambda))
    model = {'Arsig': Arsig, 'N_act': N_act, 'P': P}
    return model

###############################################################################


def gen_ar_series(AR_mod, T):
    """
    Generate an MVAR time courses

    Parameters:
        AR_mod: dictionary (output of gen_AR_model)
            Dictionary containing:\n
                * the matrices that define the model
                * N_act
                * P
        T: int
            number of time points of the generated time courses


    Returns:
        X: array, shape (N_act, T)
            the generated time courses
        AR_mod: dictionary
            Dictionary containing:\n
                * the matrices that define the model
                * N_act
                * P
    """
    Sigma = 1
    N0 = 1000
    N_act = AR_mod['N_act']
    P = AR_mod['P']
    Arsig = AR_mod['Arsig']
    x = np.random.randn(N_act, T+N0)*Sigma
    AR_mod['noise'] = x[:, P:].copy()
    y = x.copy()
    for k in range(P, T+N0):
        yloc = np.concatenate(np.flip(y[:, k-P:k], axis=1).T, axis=None)
        y[:, k] = Arsig.dot(yloc) + x[:, k]
    X = y[:, N0:].copy()
    return X, AR_mod

###############################################################################


def gen_background_tcs(P, N_bg, T):
    """
    Generate background noise time courses following univariate AR models

    Parameters:
        P: int
            order of the AR model
        N_bg: int
            number of time coursed to generate
        T: int
            number of time points of the generate time courses

    Returns:
        bg_tcs: array, shape (N_bg, T)
            the generated time courses
    """
    bg_tcs = np.zeros((N_bg, T))
    for i_bg in range(N_bg):

        # genarate the model
        lambdamax = 10
        while lambdamax < 0.9 or lambdamax >= 1:
            Arsig = np.zeros([1, 0])
            for k in range(P):
                aloc = np.random.randn(1, 1)
                Arsig = np.concatenate((Arsig, aloc), axis=1)
            E = np.eye(P)
            AA = np.concatenate((Arsig, E[0:-1, :]))
            Lambda = np.linalg.eig(AA)[0]
            lambdamax = max(abs(Lambda))
        # simulate tc
        Sigma = 1
        N0 = 1000
        x = np.random.randn(1, T+N0)*Sigma
        y = x.copy()
        for k in range(P, T+N0):
            yloc = np.concatenate(np.flip(y[:, k-P:k], axis=1).T, axis=None)
            y[:, k] = Arsig.dot(yloc) + x[:, k]
        bg_tcs[i_bg, :] = y[:, N0:].copy()

    return bg_tcs

###############################################################################


def gen_patches_sources(cortico_dist, patch_radius, seed_loc):
    """
    Define sources composing a patch with specific dirtance from the center

    Parameters:
        cortico_dist: array, shape (N_source, N_source
            cortico distances between each pair of sources in the source space
        patch_radius: float
            radius of the patch
        seed_loc: array, touple, list, shape (2, )
            index of the seed sources

    Returns:
        p1_locs: array, shape (N_p1, )
            the index of the sutces within the first patch
        p1_locs: array, shape (N_p2, )
            the index of the sutces within the second patch
    """
    tmp_id_0 = np.argsort(cortico_dist[:, seed_loc[0]])
    n_sources_0 = len(np.where(cortico_dist[:, seed_loc[0]] < patch_radius)[0])
    tmp_id_1 = np.argsort(cortico_dist[:, seed_loc[1]])
    n_sources_1 = len(np.where(cortico_dist[:, seed_loc[1]] < patch_radius)[0])

    p1_locs = tmp_id_0[0:n_sources_0]
    p2_locs = tmp_id_1[0:n_sources_1]
    return p1_locs, p2_locs

###############################################################################


def gen_coherent_patches(seed_tc, p1_locs, p2_locs, c, i_c, nperseg, nfft, fs, fmin, fmax):
    """
    Generate time courses to be assigned to the sources within the patches.
    The patches are Gaussian and have specific intracoherence level

    Parameters:
        seed_tc: array, shape (2, T)
            time courses of the seeds of each patch
        p1_locs: array, shpae (N_p1)
            indeces of the sources within patch 1
        p2_locs: array, shpae (N_p2)
            indeces of the sources within patch 2
        c: 1, 0.5, 2
            coeherence level
        i_c: not used anymore
        nperseg: int
            lenght of the epochs for the computation of the coherence
        nfft: int
            number of frequencies
        fs: float
            sampling frequency
        fmin: float
            minimum frequency for the computation of coherence
        fmax: float
            maximum frequency for the computation of coherence

    Returns:
        p1_tcs: array, shape (N_p1, T)
            time courses of the sources in patch 1
        p2_tcs: array, shape (N_p2, T)
            time courses of the sources in patch 2
    """

    # define gaussian window
    # standard deviation patch 1
    std_dev1 = (len(p1_locs)-1)/(np.sqrt(-2*np.log(0.4)))
    w1 = signal.gaussian(len(p1_locs)*2-1, std_dev1)  # weights patch 1
    w1 = w1[(len(p1_locs)-1):]
    # standard deviation patch 2
    std_dev2 = (len(p2_locs)-1)/(np.sqrt(-2*np.log(0.4)))
    w2 = signal.gaussian(len(p2_locs)*2-1, std_dev2)  # weights patch 1
    w2 = w2[(len(p2_locs)-1):]

    T = seed_tc.shape[1]
    if c == 1:
        p1_tcs = np.tile(seed_tc[0, :].reshape((1, -1)), [len(p1_locs), 1])
        p2_tcs = np.tile(seed_tc[1, :].reshape((1, -1)), [len(p2_locs), 1])
    else:
        p1_tcs = seed_tc[0, :].reshape((1, -1))
        p2_tcs = seed_tc[1, :].reshape((1, -1))

        if c == 0.5:
            rate1 = 100
            rate2 = 100
        elif c == 0.2:
            rate1 = 500
            rate2 = 300
        else:
            print('wrong coherence level, accepted values are: 1, 0.5, 0.2')

        # grow patch 1
        for i_source in range(1, len(p1_locs)):
            mean_coh = np.array([0, 1])
            while (np.min(mean_coh) < c-0.2 or np.max(mean_coh) > c+0.2):
                new_tc = fft(seed_tc[0, :].reshape((1, -1))) +\
                    np.random.randn(1, T)*(np.random.randn(1) * rate1+rate2)
                new_tc = np.real(ifft(new_tc))*w1[i_source] *\
                    (np.linalg.norm(seed_tc[0, :]) /
                     np.linalg.norm(np.real(ifft(new_tc))))

                f, conn = signal.coherence(p1_tcs, new_tc, fs=fs, window='hann',
                                           nperseg=nperseg, noverlap=nperseg//2,
                                           nfft=nperseg, detrend='constant', axis=-1)

                i_f_in = np.where((f >= fmin) & (f <= fmax))[0]
                mean_coh = abs(conn[:, i_f_in]).mean(axis=-1).copy()

            p1_tcs = np.append(p1_tcs, new_tc, axis=0)

        # grow patch 2
        for i_source in range(1, len(p2_locs)):
            mean_coh = np.array([0, 1])
            while (np.min(mean_coh) < c-0.2 or np.max(mean_coh) > c+0.2):
                new_tc = fft(seed_tc[1, :].reshape((1, -1))) + \
                    np.random.randn(1, T)*(np.random.randn(1) * rate1+rate2)
                new_tc = np.real(ifft(new_tc))*w2[i_source] *\
                    (np.linalg.norm(seed_tc[1, :]) /
                     np.linalg.norm(np.real(ifft(new_tc))))
                f, conn = signal.coherence(p2_tcs, new_tc, fs=fs, window='hann',
                                           nperseg=nperseg, noverlap=nperseg//2,
                                           nfft=nperseg, detrend='constant', axis=-1)

                i_f_in = np.where((f >= fmin) & (f <= fmax))[0]
                mean_coh = abs(conn[:, i_f_in]).mean(axis=-1).copy()

            p2_tcs = np.append(p2_tcs, new_tc, axis=0)

    p1_tcs_norm = np.linalg.norm(p1_tcs, ord='fro')
    p2_tcs_norm = np.linalg.norm(p2_tcs, ord='fro')
    return p1_tcs/p1_tcs_norm, p2_tcs/p2_tcs_norm

###############################################################################


def err_X(Lambda, X, Y, G, GGt):
    """
    Error in estimating X using the regularization parameter Lambda
            _                       2
    err_X = \   ||X_Lambda(t)-X(t)||
            /_t

    Parameters:
        Lambda: float (>0)
            regularization parameter
        X: array, shape (N_source, T)
            activity of N_source sources
        Y: array, shape (N_sensor, T)
            Sensor level regordings
        G: array, shape (N_sensor, N_source)
            leadfiel matrix
        GGt: array, shape (N_sensor, N_sensor)
            GGt = G*G^T

    Returns:
        value: float
            error
    """
    T = X.shape[1]
    if Lambda < 0:
        value = np.inf
    else:
        I = np.eye(G.shape[0])
        W_tik = G.T.dot(np.linalg.inv(GGt+Lambda*I))
        value = (1/(T*G.shape[1]))*np.linalg.norm(W_tik.dot(Y)-X, ord='fro')**2
    return value

###############################################################################


def auc(Lambda, method, G, GGt, Y, p1_sources, p2_sources, fmin, fmax, PN_matrix,
        fs, nperseg):
    """
    Compute Area Under the Curve (AUC)

    Parameters:
        Lambda: float (>0)
            regularization parameter
        method: string | list/tuple of strings
            connectivity metrics for which compute the AUC. Valid methods are
            'cpsd', 'coh', 'cohy', 'imcoh', 'plv', 'ciplv', 'ppc', 'pli',
            'pli2_unbiased', 'wpli', 'wpli2_debiased'
        G: array, shape (N_sensor, N_source)
            leadfiel matrix
        GGt: array, shape (N_sensor, N_sensor)
            GGt = G*G^T
        Y: array, shape (N_sensor, T)
            Sensor level recordings
        p1_sources: array, list, tuple, shape (N_p1, )
            indeces of the sources within patch 1
        p2_sources: array, list, tuple, shape (N_p2, )
            indeces of the sources within patch 2
        fmin: float
            minimum frequency for the computation of coherence
        fmax: float
            maximum frequency for the computation of coherence
        PN_matrix: array, shape (N_p1, N_dense-N_p1)
            matrix indicating which sources are connected (i.e. sources within
            patch 1 with sources within patch 2)
        fs: float
            sampling frequency
        nperseg: int
            lenght of the epochs for the computation of the coherence

    Returns:
        AUC_value: float
            Area under the curve
        TPF_all: array, shape (number of connectivity metrics, 20)
            True positive fraction for each connectivity metric and for each
            threshold level
        FPF_all: array, shape (number of connectivity metrics, 20)
            False positive fraction for each connectivity metric and for each
            threshold level
    """
    if Lambda < 0:
        value = 0
    else:
        if type(method) is str:
            method = [method]
        nfft = nperseg  # number of frequencies
        M = G.shape[0]
        N = G.shape[1]
        T = Y.shape[1]
        X_lam = G.T.dot(np.linalg.inv(GGt+Lambda*np.eye(M))).dot(Y)

        Conn_lam = [np.zeros((len(p1_sources), N))]*len(method)

        if 'cpsd' in method:
            method_conn = method.copy()
            method_conn.remove('cpsd')
            conn_cpsd = np.zeros((len(p1_sources), N))
            for k in range(len(p1_sources)):
                f, Connlam_row = signal.csd(X_lam[p1_sources[k], :], X_lam,
                                            fs=fs, window='hann', nperseg=nperseg,
                                            noverlap=nperseg // 2, nfft=nfft,
                                            detrend='constant', return_onesided=True,
                                            scaling='density', axis=-1)
                f_in = np.intersect1d(np.where(f >= fmin)[
                                      0], np.where(f <= fmax)[0])
                conn_cpsd[k, :] = np.mean(abs(Connlam_row[:, f_in]), axis=-1)
            Conn_lam[method.index('cpsd')] = np.delete(
                conn_cpsd, p1_sources, axis=-1)

        else:
            method_conn = method

        if len(method_conn) > 0:
            noverlap = nperseg//2
            nepo = T//(nperseg-noverlap)-1
            X_lam_re = np.zeros((nepo, N, nperseg))
            for i_epo in range(nepo):
                X_lam_re[i_epo, :, :] = X_lam[:,
                                              (nperseg-noverlap)*i_epo:(nperseg-noverlap)*i_epo+nperseg]

            indices = mne.connectivity.seed_target_indices(
                p1_sources, np.arange(N))
            (Conn, f, time, n_epochs, n_taper) = mne.connectivity.spectral_connectivity(
                X_lam_re, method=method_conn, mode='fourier', indices=indices,
                sfreq=fs, fmin=fmin, fmax=fmax, faverage=False, verbose=False)
            for i_conn in range(len(method_conn)):
                Conn_lam[method.index(method_conn[i_conn])] = \
                    np.reshape(abs(Conn[i_conn]).mean(
                        axis=-1).copy(), (len(p1_sources), N))
                Conn_lam[method.index(method_conn[i_conn])] = \
                    np.delete(Conn_lam[method.index(
                        method_conn[i_conn])], p1_sources, axis=-1)

        AUC_value = np.zeros((len(method)))
        Alpha = np.linspace(np.finfo(float).eps, 1, 20)
        Alpha = np.flip(Alpha)

        TPF_all = np.zeros((len(method), len(Alpha)))
        FPF_all = np.zeros((len(method), len(Alpha)))
        for i_conn in range(len(method)):

            TPF = np.zeros(len(Alpha))
            FPF = np.zeros(len(Alpha))
            for i_alp in range(len(Alpha)):
                aux = np.where(abs(Conn_lam[i_conn]) >= Alpha[i_alp]*np.max(abs(Conn_lam[i_conn])),
                               abs(Conn_lam[i_conn]), 0)
                PN_evaluate = np.where(aux == 0, aux, 1)

                TP = np.count_nonzero(PN_matrix == np.where(
                    PN_evaluate == 1, PN_evaluate, -1))
                FP = np.count_nonzero(PN_evaluate)-TP
                FPF[i_alp] = FP/(PN_matrix.shape[0] *
                                 PN_matrix.shape[1]-np.count_nonzero(PN_matrix))
                TPF[i_alp] = TP/np.count_nonzero(PN_matrix)

            TPF_all[i_conn, :] = TPF
            FPF_all[i_conn, :] = FPF
            AUC_value[i_conn] = -np.trapz(TPF, FPF)
    return (AUC_value, TPF_all, FPF_all)


def spectral_complexity(X, fs, nperseg, fmin, fmax):
    """
    Compute spectral complexity

                          _                                 2
    spectral_complexity = \            ||power_spectrum(f)||
                          /_fmin<f<fmax

    Parameters:
        X: array, shape (N_source, T)
            brain activuty
        fs: float
            sampling frequency
        nperseg: int
            lenght of the epochs for the computation of the coherence
        fmin: float
            minimum frequency for the computation of coherence
        fmax: float
            maximum frequency for the computation of coherence
        PN_matrix: array, shape (N_p1, N_dense-N_p1)
            matrix indicating which sources are connected (i.e. sources within
            patch 1 with sources within patch 2)

    Returns:
        sp_compl: float
            spectral complexity
    """
    nfft = nperseg
    conn_cpsd = np.zeros((X.shape[0], X.shape[0]))
    for k in range(X.shape[0]):
        f, cpsd_row = signal.csd(X[k, :], X, fs=fs, window='hann',
                                 nperseg=nperseg, noverlap=nperseg // 2,
                                 nfft=nfft, detrend='constant',
                                 return_onesided=True, scaling='density',
                                 axis=-1)
        f_in = np.intersect1d(np.where(f >= fmin)[0], np.where(f <= fmax)[0])
        conn_cpsd[k, :] = np.std(abs(cpsd_row[:, f_in]), axis=-1)
    sp_compl = np.triu(conn_cpsd).sum()/((X.shape[0]**2+X.shape[0])/2)
    return sp_compl
