import autograd
import autograd.numpy as np

import scipy
from numpy.core.umath_tests import inner1d
import torch
from torch.autograd import Variable
from torch.autograd.gradcheck import zero_gradients
from kmod import data, kernel, util
from kmod.mctest import SC_UME

gpu_mode = True
gpu_id = 2


def set_gpu_mode(is_gpu):
    global gpu_mode
    gpu_mode = is_gpu


def set_gpu_id(gpu):
    global gpu_id
    gpu_id = gpu


def optimize_3sample_criterion(datap, dataq, datar, gen_p, gen_q, Zp0,
                               Zq0, gwidth0, reg=1e-3, max_iter=100,
                               tol_fun=1e-6, disp=False, locs_bounds_frac=100,
                               gwidth_lb=None, gwidth_ub=None):
    """
    Similar to optimize_2sets_locs_widths() but constrain V=W and
    constrain the two kernels to be the same Gaussian kernel.
    Optimize one set of test locations and one Gaussian kernel width by
    maximizing the test power criterion of the UME *three*-sample test

    This optimization function is deterministic.

    Args:
        - datap: a kgof.data.Data from P (model 1)
        - dataq: a kgof.data.Data from Q (model 2)
        - datar: a kgof.data.Data from R (data generating distribution)
        - gen_p: pytorch model representing the generator p (model 1)
        - gen_q: pytorch model representing the generator q (model 2)
        - Zp0: Jxd_n numpy array. Initial value for the noise vectors of J locations.
           This is for model 1. 
        - Zq0: Jxd_n numpy array. Initial V containing J locations. For both
           This is for model 22. 
        - gwidth0: initial value of the Gaussian width^2 for both UME(P, R),
              and UME(Q, R)
        - reg: reg to add to the mean/sqrt(variance) criterion to become
            mean/sqrt(variance + reg)
        - max_iter: #gradient descent iterations
        - tol_fun: termination tolerance of the objective value
        - disp: True to print convergence messages
        - locs_bounds_frac: When making box bounds for the test_locs, extend
              the box defined by coordinate-wise min-max by std of each
              coordinate (of the aggregated data) multiplied by this number.
        - gwidth_lb: absolute lower bound on both the Gaussian width^2
        - gwidth_ub: absolute upper bound on both the Gaussian width^2

        If the lb, ub bounds are None, use fraction of the median heuristics
            to automatically set the bounds.
    Returns:
        - Z_opt: optimized noise vectors Z
        - gw_opt: optimized Gaussian width^2
        - opt_result: info from the optimization
    """
    J, dn = Zp0.shape
    Z0 = np.vstack([Zp0, Zq0])

    X, Y, Z = datap.data(), dataq.data(), datar.data()
    n, dp = X.shape

    def flatten(gwidth, V):
        return np.hstack((gwidth, V.reshape(-1)))

    def unflatten(x):
        sqrt_gwidth = x[0]
        V = np.reshape(x[1:], (2*J, -1))
        return sqrt_gwidth, V

    # Parameterize the Gaussian width with its square root (then square later)
    # to automatically enforce the positivity.
    def obj_pixel_space(sqrt_gwidth, V):
        k = kernel.KGauss(sqrt_gwidth**2)
        return -SC_UME.power_criterion(datap, dataq, datar, k, k, V, V,
                                       reg=reg)

    def flat_obj_pix(x):
        sqrt_gwidth, V = unflatten(x)
        return obj_pixel_space(sqrt_gwidth, V)

    def obj_noise_space(sqrt_gwidth, z):
        zp = z[:J]
        zq = z[J:]
        vp, vq = apply_to_models([zp, zq], [gen_p, gen_q])
        V = np.vstack([vp, vq])
        return obj_pixel_space(sqrt_gwidth, V)

    def flat_obj_noise(x):
        sqrt_gwidth, z = unflatten(x)
        return obj_noise_space(sqrt_gwidth, z)

    def grad_power_noise(x):
        """
        Compute the gradient of the power criterion with respect to the width of Gaussian
        RBF kernel and the noise vector.

        Args:
            x: 1 + 2J*d_n vector
        Returns:
            the gradient of the power criterion with respect to kernel width/latent vector
        """

        width, z = unflatten(x)
        zp = z[:J]
        zq = z[J:]
        V, [torch_zp, torch_zq] = apply_to_models([zp, zq], [gen_p, gen_q],
                                                  return_variable=True, requires_grad=True)
        V = np.vstack(V)
        grad_obj = autograd.elementwise_grad(flat_obj_pix)  # 1+(2J)*image_size input
        grad_obj_v = grad_obj(flatten(width, V))
        grad_obj_width = grad_obj_v[0]
        grad_obj_v = np.reshape(grad_obj_v[1:], [(2*J), -1])  # 2J x d_pix array

        gp_grad = compute_jacobian(torch_zp, gen_p(torch_zp).view(J, -1))  # J x d_pix x d_noise x 1 x 1
        gq_grad = compute_jacobian(torch_zq, gen_q(torch_zq).view(J, -1))  # J x d_pix x d_noise x 1 x 1
        v_grad = np.vstack([gp_grad.cpu().numpy(), gq_grad.cpu().numpy()])
        v_grad = np.squeeze(v_grad, [3, 4])
        grad_obj_z = inner1d(grad_obj_v, np.transpose(v_grad, (2, 0, 1))).flatten()

        return np.concatenate([grad_obj_width.reshape([1]), grad_obj_z])

    # Initial point
    x0 = flatten(np.sqrt(gwidth0), Z0)

    # make sure that the optimized gwidth is not too small or too large.
    XYZ = np.vstack((X, Y, Z))
    med2 = util.meddistance(XYZ, subsample=1000)**2
    fac_min = 1e-2
    fac_max = 1e2
    if gwidth_lb is None:
        gwidth_lb = max(fac_min*med2, 1e-3)
    if gwidth_ub is None:
        gwidth_ub = min(fac_max*med2, 1e5)

    # # Make a box to bound test locations
    # XYZ_std = np.std(XYZ, axis=0)
    # # XYZ_min: length-d array
    # XYZ_min = np.min(XYZ, axis=0)
    # XYZ_max = np.max(XYZ, axis=0)
    # # V_lb: 2J x dn
    # V_lb = np.tile(XYZ_min - locs_bounds_frac*XYZ_std, (2*J, 1))
    # V_ub = np.tile(XYZ_max + locs_bounds_frac*XYZ_std, (2*J, 1))
    # # (J*d+1) x 2. Take square root because we parameterize with the square
    # # root
    # x0_lb = np.hstack((np.sqrt(gwidth_lb), np.reshape(V_lb, -1)))
    # x0_ub = np.hstack((np.sqrt(gwidth_ub), np.reshape(V_ub, -1)))
    # #x0_bounds = list(zip(x0_lb, x0_ub))

    # Assuming noise coming uniform dist over unit cube
    x0_bounds = [(gwidth_lb, gwidth_ub)] + [(-1, 1)] * (2*J*dn)

    # optimize. Time the optimization as well.
    # https://docs.scipy.org/doc/scipy/reference/optimize.minimize-lbfgsb.html
    with util.ContextTimer() as timer:
        opt_result = scipy.optimize.minimize(
            flat_obj_noise, x0,
            method='L-BFGS-B', bounds=x0_bounds,
            tol=tol_fun,
            options={
                'maxiter': max_iter, 'ftol': tol_fun, 'disp': disp,
                'gtol': 1.0e-08,
            },
            jac=grad_power_noise
        )

    opt_result = dict(opt_result)
    opt_result['time_secs'] = timer.secs
    x_opt = opt_result['x']
    sq_gw_opt, Z_opt = unflatten(x_opt)
    gw_opt = sq_gw_opt**2

    assert util.is_real_num(gw_opt), 'gw_opt is not real. Was %s' % str(gw_opt)
    return Z_opt, gw_opt, opt_result


def to_torch_variable(a, shape=None, requires_grad=False):
    """Convert array a to torch.autograd.Variable"""
    if shape is None:
        shape = a.shape
    if gpu_mode:
        global gpu_id
        v = Variable(torch.from_numpy(a).float().view(shape).cuda(gpu_id),
                     requires_grad=requires_grad)
    else:
        v = Variable(torch.from_numpy(a), requires_grad=requires_grad)
        v = v.float().view(shape)
    return v


def apply_to_models(inputs, models, return_variable=False, requires_grad=False):
    """ Apply inputs to corresponding torch models (functions)
        If return_variable is True, the list of the torch variables corresponding to
        inputs is returned.
        If requires_grad is True, those variables are set to requires_grad=True.
    """
    if len(inputs) != len(models):
        raise ValueError('models and samples must have equal length')
    samples = []
    variables = []
    for i in range(len(inputs)):
        x = inputs[i]
        model = models[i]
        v = to_torch_variable(x, shape=(-1, x.shape[1], 1, 1), requires_grad=requires_grad)
        sample = model(v).cpu().data.numpy()
        sample = np.reshape(sample, [sample.shape[0], -1])
        sample = np.clip(sample, 0, 1)
        samples.append(sample)
        variables.append(v)
    if return_variable:
        return samples, variables
    else:
        return samples


# modify this later
def compute_jacobian(inputs, output):
    """
    :param inputs: Batch X Size (e.g. Depth X Width X Height)
    :param output: Batch X Classes
    :return: jacobian: Batch X Classes X Size
    """
    assert inputs.requires_grad

    num_classes = output.size()[1]

    jacobian = torch.zeros(num_classes, *inputs.size())
    grad_output = torch.zeros(*output.size())
    if inputs.is_cuda:
            global gpu_id
            grad_output = grad_output.cuda(gpu_id)
            jacobian = jacobian.cuda(gpu_id)

    for i in range(num_classes):
            zero_gradients(inputs)
            grad_output.zero_()
            grad_output[:, i] = 1
            output.backward(grad_output, retain_variables=True)
            jacobian[i] = inputs.grad.data

    return torch.transpose(jacobian, dim0=0, dim1=1)
