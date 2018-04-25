import time
import numpy as np
import tqdm
from numpy.random import randn,rand
from matplotlib import rc
import matplotlib.pyplot as pl
from scipy.interpolate import interp1d
import warnings
'''various setup code'''
rc('text', usetex=True)
warnings.filterwarnings("ignore",".*GUI is implemented.*")
pl.ion()

'''plot options'''
Lplot = 350

Nplot_mnist = 60
Nplot_mnist_last = 160
Nplot_synthetic = 1000
Dplot_synthetic = 4

'''loading data options'''
file = 'DOT'
directory = '/home/aliutkus/'
load_sketch = True
load_forward_stats = False
save_forward_stats = False
synthetic = False

input_gridding = False

''' particles parameters'''
N = 160      # number of particles

if not load_sketch:
    '''Network parameters'''
    L = 100  # number of layers
    Pt = 100  # number of percentiles for target
    nS = 5 # number of distinct patch sizes
if not load_forward_stats:
    Q = 1   # input dimension
    E = 8  # number of epochs
    Pp = 30# number of percentiles for particles

if synthetic:
    D = 200

    file = 'toy_'+file

    '''synthetic GMM data'''
    from gmm import *
    params = draw_GMM_parameters(D,30)
    T = 1000000
    (X,Y) = rand_GMM(params, T)
    Indices = np.random.permutation(T)
    X = X[:,Indices]
    Y = Y[Indices]
else:
    file = 'emnist_' + file

    if not load_sketch:
        """
        '''load MNIST training data'''
        from mnist import MNIST
        mndata = MNIST('./mnist')
        (X,Y) = mndata.load_training()
        X = np.array(X).T.astype(np.float32)
        Y = np.array(Y).T.astype(np.float32)
        file = 'mnist_'+file"""

        '''load EMNIST training data'''
        from scipy.io import loadmat
        emnist_matfile = '/home/aliutkus/dev/data/EMNIST/emnist-bymerge.mat'
        X = loadmat(emnist_matfile)['dataset'][0]['train'][0]['images'][0,0].astype(np.float32).T
        D = X.shape[0]

'''setup timer'''
start_time = time.time()


def rand_basis(n):
    '''A Random matrix distributed with Haar measure,
    From Francesco Mezzadri:
    @article{mezzadri2006generate,
        title={How to generate random matrices from the classical compact groups},
        author={Mezzadri, Francesco},
        journal={arXiv preprint math-ph/0609050},
        year={2006}}
    '''
    z = np.random.randn(n,n)
    q,r = np.linalg.qr(z)
    d = np.diagonal(r)
    ph = d/np.absolute(d)
    q = np.multiply(q,ph,q)
    return q

def projection_parameters(l,L):
    np.random.seed(l * L)
    order = np.random.permutation(D)
    invorder = np.argsort(order)
    if (l +1 ) % 2:
        s = np.random.choice(S)
    else:
        s = D
    R = [rand_basis(s) for r in range(0, D, s)]
    return (order, invorder,s, R)

'''Get size of patches'''
def factors(n):
    from functools import reduce
    return set(reduce(list.__add__,
                ([i, int(n//i)] for i in range(1, int(n**0.5) + 1) if not n % i)))

'''Load data or prepare sketch'''
if load_sketch:
    data = np.load('%ssketch_%s.npy'%(directory,file))[()]
    CDF_target = data['CDF_target']
    (L, Pt, D) = CDF_target.shape
    percentiles_t = data['percentiles']
    S = data['S']
else:
    percentiles_t = np.linspace(0., 100., Pt)  # percentiles for target

    CDF_target = np.zeros((L, Pt, D),dtype=np.float32)

    #create the size of patches
    S = list(factors(D))
    S.sort()
    S = np.array(S)
    S = S[-min(nS, S.size):]
    print('Length of patches', S)

    #sketch the data
    for l in tqdm.tqdm(range(L),desc='Sketching the data. Projection'):
    #each layer is the application of a random basis to the data
            if l==0:
                Hf = X.copy()
            else:
                (order, invorder,s, R) = projection_parameters(l)
                Hf = np.zeros_like(X)
                for (ir, r) in enumerate(range(0, D, s)):
                    #CDF_target[l,:,r:r+s] = np.percentile(R[ir].T @ X[order[r:r+s],:], percentiles, axis=1)
                    Hf[r:r + s,:] = R[ir].T @ X[order[r:r+s],:]
            CDF_target[l, ...] = np.percentile(Hf, percentiles_t, axis=1)

    np.save(directory + 'sketch_'+file, {'CDF_target': CDF_target,
                               'S': S,
                               'percentiles': percentiles_t})
    if not synthetic:
        X=None # free memory in case of EMNIST


L0 = L

if load_forward_stats:
    data = np.load('%sforward_%s.npy' % (directory, file))[()]
    CDF_forward = data['CDF_forward']
    percentiles_p = data['percentiles']
    E = CDF_forward.shape[0]
    Q = data['Q']
else:
    CDF_forward = np.zeros((E, L, Pp, D),dtype=np.float32)
    percentiles_p = np.linspace(0., 100., Pp)  # percentiles for particles



def transport(CDF_source,CDF_target,u):
    """1D transport
    CDF_source: source quantiles Pp x D
    CDF_target: target quantiles Pt x D
    u:  data to transport: D x K

    assuming the 'percentiles' variable is defined globally
    """
    D = CDF_source.shape[-1]
    z = np.zeros(u.shape)

    for d in range(D):
        F    = interp1d(CDF_source[:, d], percentiles_p, kind='linear', bounds_error=False, fill_value='extrapolate')
        Ginv = interp1d(percentiles_t, CDF_target[:, d], kind='linear', bounds_error=False, fill_value='extrapolate')
        ud = np.maximum(CDF_source[0,d],u[d,:])
        ud = np.minimum(CDF_source[-1, d], ud)
        #ud = u[d,:]
        zd = F(ud)
        zd = np.maximum(zd,0.)
        zd = np.minimum(zd, 100.)
        z[d, :] = Ginv(zd)
    return z


'''generate particles'''
if input_gridding:
    N =int(np.sqrt(N))
    N = N**2
    u1,u2=np.meshgrid(np.linspace(0,1,np.sqrt(N)),np.linspace(0,1,np.sqrt(N)))
    u = np.concatenate((u1.flatten()[None,:],u2.flatten()[None,:]))
else:
    np.random.seed(int(time.time()))
    u = rand(Q,N)


'''generate embedding vectors'''
if Q<D:
    np.random.seed(0)
    A = randn(D,Q)

    # set initial states in high dimension
    Xf =A@u
else:
    Xf = u.copy()

Xmean = 0.
count = 0.

for e in tqdm.tqdm(range(E),desc='Epoch'):
    #epochs over the different layers

    for l in tqdm.tqdm(range(L),desc='Layer'):
    #each layer is the application of a random basis to the data

        if l == 0:
            #first layer is just identity
            Pf = Xf.copy()
        if l>0:
            # initializing the seed in a deterministic way so as to avoid storing R
            (order, invorder, s, R) = projection_parameters(l,L0)
            for (ir,r) in enumerate(range(0, D, s)):
                Pf[r:r+s,:]= R[ir].T @ Xf[order[r:r+s],:]

        #compute statistics if not loaded
        if not load_forward_stats:
            CDF_forward[e, l, ...] = np.percentile(Pf, percentiles_p, axis=1)

        #transport current samples
        projected_Xf = transport(CDF_forward[e,l,...],CDF_target[l,...], Pf)  #- Pf

        if l>0:
            for (ir, r) in enumerate(range(0, D, s)):
                projected_Xf[r:r + s,:] = R[ir] @ projected_Xf[r:r+s,:]
            projected_Xf = projected_Xf[invorder]

        Xf = projected_Xf

        if e >=E-2:
            if l==0:
                Xmean = Xf
            else:
                count += 1.
                Xmean += (Xf-Xmean)/count

        # save data for the last layer
        if (l == L - 1) and not load_forward_stats and save_forward_stats:
                    np.save(directory + 'forward_'+file, {'CDF_forward': CDF_forward[:e+1,...],'percentiles':percentiles_p,'Q':Q})


        ''' Now do all the plotting'''
        last = False
        if (l == L - 1) and (e == E - 1):
            # set the next block as blocking
            pl.ioff()
            last = True
            Nplot_mnist=Nplot_mnist_last
            #prints the total computing time
            print('Total time:', time.time() - start_time)

        if not (l+1)%Lplot or( (e==E-1) and (l==(L-1))):

            '''A/ plot a few examples of generated forward data'''
            if synthetic:
                pl.figure(1)
                pl.clf()
                ncol = max(min(Dplot_synthetic-1,4),np.ceil(np.sqrt(Dplot_synthetic - 1)))
                nlines = np.ceil(float(Dplot_synthetic - 1.) / ncol)
                for dplot in range(Dplot_synthetic - 1):
                    pl.subplot(nlines, ncol, dplot + 1)
                    pl.gca().axes.xaxis.set_ticklabels([])
                    pl.gca().axes.yaxis.set_ticklabels([])

                    # display the true toy data and the one generated
                    pl.plot(X[dplot, :min(T,Nplot_synthetic)], X[dplot + 1, :min(T,Nplot_synthetic)], 'rx')
                    pl.plot(Xf[dplot, :min(Nplot_synthetic, N)], Xf[dplot + 1, :min(Nplot_synthetic, N)], 'b+')

                    pl.grid(True)
                    pl.xlabel('$x_{%d}$' % dplot)
                    pl.ylabel('$x_{%d}$' % (dplot + 1))
                pl.legend(('true', 'generated'))
            else:
                current = 0
                nb_batches = 1
                if last:
                    nb_batches = 1
                for batch in range(nb_batches):
                    pl.figure(10+batch)
                    pl.clf()
                    ncol = max(min(Nplot_mnist, 4), np.ceil(np.sqrt(Nplot_mnist)))
                    nlines = np.ceil(float(Nplot_mnist) / ncol)
                    for k in range(Nplot_mnist):
                        pl.subplot(nlines,ncol, k + 1)
                        if e>=E-2:
                            Xplot = Xmean
                        else:
                            Xplot = Xf
                        pl.imshow(np.reshape(Xplot[:, k+current], [28, 28]).T, aspect='auto', interpolation='nearest', cmap='gray')
                        pl.axis('off')
                    current += Nplot_mnist

            ''' B/ Display the histograms of projections'''
            '''if not load_data:
                pl.figure(2)
                pl.clf()
                Nhist = 5
                for ip in range(Nhist):
                    pl.subplot(Nhist, 1, ip + 1)
                    if l==0:
                        Pf = Xf.copy()
                        Hf = X.copy()
                    else:
                        Pf = np.zeros_like(Xf)
                        Hf = np.zeros_like(X)
                        for (ir, r) in enumerate(range(0, D, s)):
                            Pf[r:r + s, :] = R[ir].T @ Xf[order[r:r + s], :]
                            Hf[r:r + s, :] = R[ir].T @ X[order[r:r + s], :]
                    pl.hist([Hf[ip, :],Pf[ip, :]], 100,histtype = 'step',label = ['Projected target','Projected forward particles'],normed = True)
                    if not ip:
                        pl.legend()'''

            ''' D/ draw '''
            pl.pause(0.1)
            pl.draw()
            pl.show()

