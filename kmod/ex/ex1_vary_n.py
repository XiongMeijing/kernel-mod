"""Simulation to get the test power vs increasing sample size"""

__author__ = 'wittawat'

# Two-sample test
import freqopttest.tst as tst
import kmod
from kmod import data, density, kernel, util
from kmod import mctest as mct
import kmod.glo as glo
import kmod.mctest as mct
import kmod.model as model
import kgof.density as density
# goodness-of-fit test
import kgof.goftest as gof

# need independent_jobs package 
# https://github.com/karlnapf/independent-jobs
# The independent_jobs and kgof have to be in the global search path (.bashrc)
import independent_jobs as inj
from independent_jobs.jobs.IndependentJob import IndependentJob
from independent_jobs.results.SingleResult import SingleResult
from independent_jobs.aggregators.SingleResultAggregator import SingleResultAggregator
from independent_jobs.engines.BatchClusterParameters import BatchClusterParameters
from independent_jobs.engines.SerialComputationEngine import SerialComputationEngine
from independent_jobs.engines.SlurmComputationEngine import SlurmComputationEngine
from independent_jobs.tools.Log import logger
#import numpy as np
import autograd.numpy as np
import os
import sys 

"""
All the method functions (starting with met_) return a dictionary with the
following keys:
    - test: test object. (may or may not return to save memory)
    - test_result: the result from calling perform_test(te).
    - time_secs: run time in seconds 

    * A method function may return an empty dictionary {} if the inputs are not
    applicable. For example, if density functions are not available, but the
    method function is FSSD which needs them.

All the method functions take the following mandatory inputs:
    - P: a kmod.model.Model (candidate model 1)
    - Q: a kmod.model.Model (candidate model 2)
    - data_source: a kgof.data.DataSource for generating the data (i.e., draws
          from R)
    - n: total sample size. Each method function should draw exactly the number
          of points from data_source.
    - r: repetition (trial) index. Drawing samples should make use of r to
          set the random seed.
    -------
    - A method function may have more arguments which have default values.
"""
def sample_pqr(ds_p, ds_q, ds_r, n, r, only_from_r=False):
    """
    Generate three samples from the three data sources given a trial index r.
    All met_ functions should use this function to draw samples. This is to
    provide a uniform control of how samples are generated in each trial.

    ds_p: DataSource for model P
    ds_q: DataSource for model Q
    ds_r: DataSource for the data distribution R
    n: sample size to draw from each
    r: trial index

    Return (datp, datq, datr) where each is a Data containing n x d numpy array
    Return datr if only_from_r is True.
    """
    datr = ds_r.sample(n, seed=r+3)
    if only_from_r:
        return datr
    datp = ds_p.sample(n, seed=r+1)
    datq = ds_q.sample(n, seed=r+2)
    return datp, datq, datr

#-------------------------------------------------------

def met_sc_umeJ1_rand(P, Q, data_source, n, r, J=1, use_1set_locs=False):
    """
    UME-based three-sample test. 
        * Use J=1 test location by default. 
        * Use two sets of test locations by default: V and W, each having J
            locations.  Will constrain V=W if use_1set_locs=True.
        * The test locations are selected at random from the data. Selected
            points are removed for testing.
        * Gaussian kernels for the two UME statistics. Median heuristic is used
            to select each width.
    """
    if not P.has_datasource() or not Q.has_datasource():
        # Not applicable. Return {}.
        return {}
    assert J >= 1

    ds_p = P.get_datasource()
    ds_q = Q.get_datasource()
    # sample some data 
    datp, datq, datr = sample_pqr(ds_p, ds_q, data_source, n, r, only_from_r=False)

    # Start the timer here
    with util.ContextTimer() as t:

        # remove the first J points from each set 
        X, Y, Z = datp.data(), datq.data(), datr.data()

        # containing 3*J points
        pool3J = np.vstack((X[:J, :], Y[:J, :], Z[:J, :]))
        X, Y, Z = [np.delete(a, range(J), 0) for a in [X, Y, Z]]
        datp, datq, datr = [data.Data(a) for a in [X, Y, Z]]
        assert X.shape[0] == Y.shape[0]
        assert Y.shape[0] == Z.shape[0]
        assert Z.shape[0] == n-J

        if use_1set_locs:
            # randomly select J points from the pool3J for the J test locations
            V = util.subsample_rows(pool3J, J, r)
            W = V
        else:
            # use two sets of locations: V and W
            VW = util.subsample_rows(pool3J, 2*J, r)
            V = VW[:J, :]
            W = VW[J:, :]

        # median heuristic to set the Gaussian widths
        medxz = util.meddistance(np.vstack((X, Z)), subsample=1000)
        medyz = util.meddistance(np.vstack((Z, Y)), subsample=1000)

        # 2 Gaussian kernels
        k = kernel.KGauss(sigma2=medxz**2)
        l = kernel.KGauss(sigma2=medyz**2)

        # construct the test
        scume = mct.SC_UME(datp, datq, k, l, V, W, alpha=alpha)
        scume_rand_result = scume.perform_test(datr)

    return {
            # This key "test" can be removed. Storing V, W can take quite a lot
            # of space, especially when the input dimension d is high.
            #'test':scume, 
            'test_result': scume_rand_result, 'time_secs': t.secs}


#def job_fssdJ1q_med(p, data_source, tr, te, r, J=1, null_sim=None):
#    """
#    FSSD test with a Gaussian kernel, where the test locations are randomized,
#    and the Gaussian width is set with the median heuristic. Use full sample.
#    No training/testing splits.

#    p: an UnnormalizedDensity
#    data_source: a DataSource
#    tr, te: Data
#    r: trial number (positive integer)
#    """
#    if null_sim is None:
#        null_sim = gof.FSSDH0SimCovObs(n_simulate=2000, seed=r)

#    # full data
#    data = tr + te
#    X = data.data()
#    with util.ContextTimer() as t:
#        # median heuristic 
#        med = util.meddistance(X, subsample=1000)
#        k = kernel.KGauss(med**2)
#        V = util.fit_gaussian_draw(X, J, seed=r+1)

#        fssd_med = gof.FSSD(p, k, V, null_sim=null_sim, alpha=alpha)
#        fssd_med_result = fssd_med.perform_test(data)
#    return { 'test_result': fssd_med_result, 'time_secs': t.secs}

#def job_fssdJ5q_med(p, data_source, tr, te, r):
#    """
#    FSSD. J=5
#    """
#    return job_fssdJ1q_med(p, data_source, tr, te, r, J=5)


# Define our custom Job, which inherits from base class IndependentJob
class Ex1Job(IndependentJob):
   
    def __init__(self, aggregator, P, Q, data_source, prob_label, rep, met_func, n):
        #walltime = 60*59*24 
        walltime = 60*59
        memory = int(tr_proportion*n*1e-2) + 50

        IndependentJob.__init__(self, aggregator, walltime=walltime,
                               memory=memory)
        # P, P are kmod.model.Model
        self.P = P
        self.Q = Q
        self.data_source = data_source
        self.prob_label = prob_label
        self.rep = rep
        self.met_func = met_func
        self.n = n

    # we need to define the abstract compute method. It has to return an instance
    # of JobResult base class
    def compute(self):

        P = self.P
        Q = self.Q
        data_source = self.data_source 
        r = self.rep
        n = self.n
        met_func = self.met_func
        data = data_source.sample(n, seed=r)
        prob_label = self.prob_label

        logger.info("computing. %s. prob=%s, r=%d,\
                n=%d"%(met_func.__name__, prob_label, r, n))
        with util.ContextTimer() as t:
            job_result = met_func(P, Q, data_source, n, r)

            # create ScalarResult instance
            result = SingleResult(job_result)
            # submit the result to my own aggregator
            self.aggregator.submit_result(result)
            func_name = met_func.__name__

        logger.info("done. ex2: %s, prob=%s, r=%d, n=%d. Took: %.3g s "%(func_name,
            prob_label, r, n, t.secs))

        # save result
        fname = '%s-%s-n%d_r%d_a%.3f_trp%.2f.p' \
                %(prob_label, func_name, n, r, alpha, tr_proportion)
        glo.ex_save_result(ex, job_result, prob_label, fname)

# This import is needed so that pickle knows about the class Ex1Job.
# pickle is used when collecting the results from the submitted jobs.
from kmod.ex.ex1_vary_n import Ex1Job
from kmod.ex.ex1_vary_n import met_sc_umeJ1_rand

#--- experimental setting -----
ex = 1

# significance level of the test
alpha = 0.05

# Proportion of training sample relative to the full sample size n
tr_proportion = 0.5

# repetitions for each sample size 
reps = 3

# tests to try
method_funcs = [ 
    met_sc_umeJ1_rand, 
   ]

# If is_rerun==False, do not rerun the experiment if a result file for the current
# setting of (ni, r) already exists.
is_rerun = False
#---------------------------

def get_ns_pqrsource(prob_label):
    """
    Return (ns, P, Q, ds), a tuple of
    - ns: a list of sample sizes n's
    - P: a kmod.model.Model representing the model P
    - Q: a kmod.model.Model representing the model Q
    - ds: a DataSource. The DataSource generates sample from R.

    * (P, Q, ds) together specity a three-sample (or model comparison) problem.
    """

    prob2tuples = { 
        # p,q,r all standard normal in 1d. Mean shift problem. Unit variance.
        # This is the simplest possible problem.
        'stdnormal_shift_d1': (
            [200, 400, 600, 800],
            # p = N(0.4, 1)
            model.ComposedModel(p=density.IsotropicNormal(np.array([0.4]), 1.0)),
            # q = N(0.2, 1). q is closer to r. Should reject.
            model.ComposedModel(p=density.IsotropicNormal(np.array([0.2]), 1.0)),
            # data generating distribution r = N(0, 1)
            data.DSIsotropicNormal(np.array([0.0]), 1.0),
        ),

    }
    if prob_label not in prob2tuples:
        raise ValueError('Unknown problem label. Need to be one of %s'%str(list(prob2tuples.keys()) ))
    return prob2tuples[prob_label]


def run_problem(prob_label):
    """Run the experiment"""
    # ///////  submit jobs //////////
    # create folder name string
    #result_folder = glo.result_folder()
    from kmod.config import expr_configs
    tmp_dir = expr_configs['scratch_path']
    foldername = os.path.join(tmp_dir, 'kmod_slurm', 'e%d'%ex)
    logger.info("Setting engine folder to %s" % foldername)

    # create parameter instance that is needed for any batch computation engine
    logger.info("Creating batch parameter instance")
    batch_parameters = BatchClusterParameters(
        foldername=foldername, job_name_base="e%d_"%ex, parameter_prefix="")

    # Use the following line if Slurm queue is not used.
    engine = SerialComputationEngine()
    #engine = SlurmComputationEngine(batch_parameters, partition='wrkstn,compute')
    #engine = SlurmComputationEngine(batch_parameters)
    n_methods = len(method_funcs)

    # problem setting
    ns, P, Q, ds, = get_ns_pqrsource(prob_label)

    # repetitions x len(ns) x #methods
    aggregators = np.empty((reps, len(ns), n_methods ), dtype=object)

    for r in range(reps):
        for ni, n in enumerate(ns):
            for mi, f in enumerate(method_funcs):
                # name used to save the result
                func_name = f.__name__
                fname = '%s-%s-n%d_r%d_a%.3f_trp%.2f.p' \
                        %(prob_label, func_name, n, r, alpha, tr_proportion)
                if not is_rerun and glo.ex_file_exists(ex, prob_label, fname):
                    logger.info('%s exists. Load and return.'%fname)
                    job_result = glo.ex_load_result(ex, prob_label, fname)

                    sra = SingleResultAggregator()
                    sra.submit_result(SingleResult(job_result))
                    aggregators[r, ni, mi] = sra
                else:
                    # result not exists or rerun
                    job = Ex1Job(SingleResultAggregator(), P, Q, ds, prob_label,
                            r, f, n)

                    agg = engine.submit_job(job)
                    aggregators[r, ni, mi] = agg

    # let the engine finish its business
    logger.info("Wait for all call in engine")
    engine.wait_for_all()

    # ////// collect the results ///////////
    logger.info("Collecting results")
    job_results = np.empty((reps, len(ns), n_methods), dtype=object)
    for r in range(reps):
        for ni, n in enumerate(ns):
            for mi, f in enumerate(method_funcs):
                logger.info("Collecting result (%s, r=%d, n=%rd)" %
                        (f.__name__, r, n))
                # let the aggregator finalize things
                aggregators[r, ni, mi].finalize()

                # aggregators[i].get_final_result() returns a SingleResult instance,
                # which we need to extract the actual result
                job_result = aggregators[r, ni, mi].get_final_result().result
                job_results[r, ni, mi] = job_result

    #func_names = [f.__name__ for f in method_funcs]
    #func2labels = exglobal.get_func2label_map()
    #method_labels = [func2labels[f] for f in func_names if f in func2labels]

    # save results 
    results = {'job_results': job_results, 
            'P': P, 'Q': Q,
            'data_source': ds, 
            'alpha': alpha, 'repeats': reps, 'ns': ns,
            'tr_proportion': tr_proportion,
            'method_funcs': method_funcs, 'prob_label': prob_label,
            }
    
    # class name 
    fname = 'ex%d-%s-me%d_rs%d_nmi%d_nma%d_a%.3f_trp%.2f.p' \
        %(ex, prob_label, n_methods, reps, min(ns), max(ns), alpha,
                tr_proportion)

    glo.ex_save_result(ex, results, fname)
    logger.info('Saved aggregated results to %s'%fname)

#---------------------------
def main():
    if len(sys.argv) != 2:
        print('Usage: %s problem_label'%sys.argv[0])
        sys.exit(1)
    prob_label = sys.argv[1]
    run_problem(prob_label)

if __name__ == '__main__':
    main()

