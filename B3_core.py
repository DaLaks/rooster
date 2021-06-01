from B3A_isotope import Isotope
from B3B_mix import Mix
from multiprocessing import Pool

import B3_coreF
import multiprocessing as mp
import numpy
import sys
import time

#--------------------------------------------------------------------------------------------------
class Core:

    #----------------------------------------------------------------------------------------------
    # constructor: self is a 'core' object created in B
    def __init__(self, reactor):

        # INITIALIZATION
        if 'pointkinetics' in reactor.solve:
            self.power = 1
            self.ndnp = len(reactor.control.input['betaeff'])
            self.tlife = reactor.control.input['tlife']
            self.dnplmb = reactor.control.input['dnplmb']
            self.betaeff = reactor.control.input['betaeff']
            self.cdnp = [0] * self.ndnp
            for i in range(self.ndnp) :
                self.cdnp[i] = self.betaeff[i]*self.power/(self.dnplmb[i]*self.tlife)

        if 'spatialkinetics' in reactor.solve:

            # correct!
            self.rtol = 1e-6
            self.atol = 1e-6

            # number of energy groups
            self.ng = reactor.control.input['ng']

            # core mesh
            self.nz = len(reactor.control.input['stack'][0]['mixid'])
            for i in range(len(reactor.control.input['stack'])):
                if len(reactor.control.input['stack'][i]['mixid']) != self.nz:
                    print('****ERROR: all stacks should have the same number of axial nodes.')
                    sys.exit()
            # add bottom and top layers for boundary conditions
            self.nz += 2
            self.ny = len(reactor.control.input['coremap'])
            self.nx = len(reactor.control.input['coremap'][0])
            for i in range(self.nx):
                if len(reactor.control.input['coremap'][i]) != self.nx:
                    print('****ERROR: all coremap cards should have the same number of nodes.')
                    sys.exit()

            # initialize flux
            self.flux = numpy.ones(shape=(self.nz, self.ny, self.nx, self.ng), order='F')

            # create a list of all isotopes
            self.isoname = [x['isoid'][i] for x in reactor.control.input['mix'] for i in range(len(x['isoid']))]
            #remove duplicates
            self.isoname = list(dict.fromkeys(self.isoname))
            # create an object for every isotope
            self.niso = len(self.isoname)
            self.iso = []
            for i in range(self.niso):
                self.iso.append(Isotope(self.isoname[i], reactor))
                self.iso[i].print_xs = True

            # create an object for every mix
            self.nmix = len(reactor.control.input['mix'])
            self.mix = []
            for i in range(self.nmix):
                self.mix.append(Mix(i, self, reactor))

            # calculate sig0 and macroscopic cross sections
            for i in range(self.nmix):
                self.mix[i].calculate_sig0(self, reactor)
                self.mix[i].calculate_sigt(self, reactor)
                self.mix[i].calculate_siga(self, reactor)
                self.mix[i].calculate_sigp(self, reactor)
                self.mix[i].calculate_chi(self)
                self.mix[i].calculate_sigs(self, reactor)
                self.mix[i].calculate_sign2n(self, reactor)
                self.mix[i].update_xs = False
                self.mix[i].print_xs = True

                tac = time.time()
                print('{0:.3f}'.format(tac - reactor.tic), ' s | mix cross sections processed: ', self.mix[i].mixid)
                reactor.tic = tac

            # initialize map
            self.geom = reactor.control.input['coregeom']['geom']
            self.map = {'dz':[], 'imix':[], 'ipipe':[]}
            mixid_list = [self.mix[i].mixid for i in range(self.nmix)]
            self.nstack = len(reactor.control.input['stack'])
            stackid_list = [reactor.control.input['stack'][i]['stackid'] for i in range(self.nstack)]
            self.npipe = len(reactor.control.input['pipe'])
            pipeid_list = [reactor.control.input['pipe'][i]['id'] for i in range(self.npipe)]
            # vacuum is -1 and reflective is -2
            bc = [-1,-2]
            for iz in range(self.nz):
                self.map['imix'].append([])
                self.map['ipipe'].append([])
                for iy in range(self.ny):
                    self.map['imix'][iz].append([])
                    self.map['ipipe'][iz].append([])
                    if iz == 0:
                        # bottom boundary conditions
                        botBC = int(reactor.control.input['coregeom']['botBC'])
                        for ix in range(self.nx):
                            self.map['imix'][iz][iy].append(bc[botBC])
                    elif iz == self.nz-1:
                        # top boundary conditions
                        topBC = int(reactor.control.input['coregeom']['topBC'])
                        for ix in range(self.nx):
                            self.map['imix'][iz][iy].append(bc[topBC])
                    else:
                        for ix in range(self.nx):
                            id = reactor.control.input['coremap'][iy][ix]
                            if isinstance(id, float):
                                self.map['imix'][iz][iy].append(bc[int(id)])
                            else:
                                if id not in stackid_list:
                                    print('****ERROR: stack id (' + id + ') in coremap card not specified in stack card.')
                                    sys.exit()
                                else:
                                    # index of stack
                                    istack = stackid_list.index(id)
                                    # id of mix at (ix, iy, iz)
                                    mixid = reactor.control.input['stack'][istack]['mixid'][iz-1]
                                    if mixid not in mixid_list:
                                        print('****ERROR: mix id in stack card (' + mixid + ') not specified in mix card.')
                                        sys.exit()
                                    else:
                                        # index of stack
                                        imix = mixid_list.index(mixid)
                                        self.map['imix'][iz][iy].append(imix)
                                    # id of pipe at (ix, iy, iz)
                                    pipeid = reactor.control.input['stack'][istack]['pipeid'][iz-1]
                                    if pipeid not in pipeid_list:
                                        print('****ERROR: pipe id (' + pipeid + ') in stack card not specified in pipe card.')
                                        sys.exit()
                                    else:
                                        # index of pipe
                                        ipipe = pipeid_list.index(pipeid)
                                        # id of pipenode at (ix, iy, iz)
                                        pipenode = reactor.control.input['stack'][istack]['pipenode'][iz-1]
                                        if pipenode > reactor.control.input['pipe'][ipipe]['nnodes']:
                                            print('****ERROR: pipenode index (' + pipenode + ') in stack card is bigger than number of nodes in pipe ' + pipeid + '.')
                                            sys.exit()
                                        else:
                                            self.map['ipipe'][iz][iy].append((ipipe,pipenode))
                                # node height
                                if len(self.map['dz']) < iz:
                                    self.map['dz'].append(reactor.control.input['pipe'][ipipe]['len']/reactor.control.input['pipe'][ipipe]['nnodes'])
            # core assembly pitch
            self.pitch = 100*reactor.control.input['coregeom']['pitch']
            # side area to volume ratio of control volume 
            if self.geom == 'square':
                self.aside_over_v = 1/self.pitch
            elif self.geom == 'hex':
                self.aside_over_v = 2/(3*self.pitch)

            print(B3_coreF.solve_eigenvalue_problem.__doc__)
            sigt = numpy.array([[self.mix[imix].sigt[ig] for ig in range(self.ng)] for imix in range(self.nmix)], order='F')
            sigp = numpy.array([[self.mix[imix].sigp[ig] for ig in range(self.ng)] for imix in range(self.nmix)], order='F')
            nsigs = numpy.array([len(self.mix[imix].sigs) for imix in range(self.nmix)], order='F')
            sigs = numpy.zeros(shape=(self.nmix, max(nsigs)), order='F')
            for imix in range(self.nmix):
                for indx in range(nsigs[imix]):
                    sigs[imix][indx] = self.mix[imix].sigs[indx][1]
            B3_coreF.solve_eigenvalue_problem(self.nz, self.ny, self.nx, self.ng, self.nmix, self.flux, self.map['imix'], sigt, sigp, nsigs, sigs, self.pitch, self.map['dz'])
            sys.exit()

            #self.solve_eigenvalue_problem(reactor)
            self.k = [1]
    #----------------------------------------------------------------------------------------------
    # create right-hand side list: self is a 'core' object created in B
    def calculate_rhs(self, reactor, t):

        # construct right-hand side list
        rhs = []
        if 'pointkinetics' in reactor.solve:
            # read input parameters
            rho = reactor.control.signal['RHO_INS']
            dpowerdt = self.power * (rho - sum(self.betaeff)) / self.tlife
            dcdnpdt = [0] * self.ndnp
            for i in range(self.ndnp) :
                dpowerdt += self.dnplmb[i]*self.cdnp[i]
                dcdnpdt[i] = self.betaeff[i]*self.power/self.tlife - self.dnplmb[i]*self.cdnp[i]
            rhs = [dpowerdt] + dcdnpdt

        if 'spatialkinetics' in reactor.solve:
            for i in range(self.nmix):
                if self.mix[i].update_xs:
                    self.mix[i].calculate_sig0(self, reactor)
                    self.mix[i].calculate_sigt(self, reactor)
                    self.mix[i].calculate_siga(self, reactor)
                    self.mix[i].calculate_sigp(self, reactor)
                    self.mix[i].calculate_chi(self)
                    self.mix[i].calculate_sigs(self, reactor)
                    self.mix[i].calculate_sign2n(self, reactor)
                    self.mix[i].update_xs = False
                    self.mix[i].print_xs = True

            rhs += []

        return rhs

    #----------------------------------------------------------------------------------------------
    # solve steady-state eigenvalue problem
    def solve_eigenvalue_problem(self, reactor):

        # initialize fission source
        self.qf = [[[1e-6 for ix in range(self.nx)] for iy in range(self.ny)] for iz in range(self.nz)]
        # eigenvalue self.k equal to ratio of total fission source at two iterations. 
        # flux is normalise to total fission cource = 1 at previous iteration 
        self.k = [1]

        #print(self.build_matrix_eigenvalue_problem(1))
        
        converge_qf = False
        converge_k = False
        # initialize multiprocessing pool
        #pool = Pool(20)
        while not converge_qf and not converge_k:
            self.solve_flux_eigenvalue_problem(reactor)

            ## initialize flux convergence flag
            #converge_flux = False
            #iter = 0
            #while not converge_flux and iter < 10:
            #    iter += 1
            #    converge_flux = True
            #    for iz in range(1,self.nz-1):
            #        flux = self.solve_flux_eigenvalue_problem(iz)
            #        k = 0
            #        for iy in range(self.ny):
            #            for ix in range(self.nx):
            #                imix = self.map['imix'][iz][iy][ix]
            #                # if (ix, iy, ]iz) is not a boundary condition node, i.e. not -1 (vac) and not -2 (ref)
            #                if imix >= 0:
            #                    for ig in range(self.ng):
            #                        if converge_flux : converge_flux = abs(flux[k] - self.flux[iz][iy][ix][ig]) < self.rtol*abs(flux[k]) + self.atol
            #                        self.flux[iz][iy][ix][ig] = flux[k]
            #                        k += 1

            #arg1, arg2, arg3 = [], [], []
            #for iz in range(self.nz):
            #    for iy in range(self.ny):
            #        for ix in range(self.nx):
            #            imix = self.map['imix'][iz][iy][ix]
            #            # if (ix, iy, iz) is not a boundary condition node, i.e. not -1 (vac) and not -2 (ref)
            #            if imix >= 0:
            #                arg1.append(ix)
            #                arg2.append(iy)
            #                arg3.append(iz)
            #            else:
            #                self.converge_flux[iz][iy][ix] = True
            #list(map(self.solve_flux_eigenvalue_problem, arg1, arg2, arg3))
            
            #if __name__ == 'B3_core':
            #    flux = pool.map(self.solve_flux_eigenvalue_problem, range(1,self.nz-1))
            #    converge_flux = True
            #    for iz in range(self.nz):
            #        k = 0
            #        for iy in range(self.ny):
            #            for ix in range(self.nx):
            #                imix = self.map['imix'][iz][iy][ix]
            #                # if (ix, iy, iz) is not a boundary condition node, i.e. not -1 (vac) and not -2 (ref)
            #                if imix >= 0:
            #                    for ig in range(self.ng):
            #                        if converge_flux : converge_flux = abs(flux[iz-1][k] - self.flux[iz][iy][ix][ig]) < self.rtol*abs(flux[iz-1][k]) + self.atol
            #                        self.flux[iz][iy][ix][ig] = flux[iz-1][k]
            #                        k += 1

            converge_qf = True
            for iz in range(self.nz):
                for iy in range(self.ny):
                    for ix in range(self.nx):
                        imix = self.map['imix'][iz][iy][ix]
                        # if (ix, iy, iz) is not a boundary condition node, i.e. not -1 (vac) and not -2 (ref)
                        if imix >= 0:
                            xs = self.mix[imix]
                            qf = 0
                            for ig in range(self.ng):
                                qf += xs.sigp[ig]*self.flux[iz][iy][ix][ig]
                            if converge_qf : converge_qf = abs(qf - self.qf[iz][iy][ix]) < self.rtol*abs(qf) + self.atol
                            self.qf[iz][iy][ix] = qf

            converge_k = True
            k = 0
            for iz in range(self.nz):
                for iy in range(self.ny):
                    for ix in range(self.nx):
                        imix = self.map['imix'][iz][iy][ix]
                        # if (ix, iy, iz) is not a boundary condition node, i.e. not -1 (vac) and not -2 (ref)
                        if imix >= 0:
                            for ig in range(self.ng):
                                k += self.qf[iz][iy][ix]
            converge_k = abs(k - self.k[-1]) < self.rtol*abs(k) + self.atol
            self.k.append(k)
            print('k-effective: ', '{0:12.5f} '.format(self.k[-1]))
        # close multiprocessing pool
        #pool.close() 

    #----------------------------------------------------------------------------------------------
    # calculate and return flux in plane iz for steady-state eigenvalue problem
    
    def solve_flux_eigenvalue_problem(self, reactor):

        # initialize flux convergence flag
        converge_flux = False
        niter = 0
        while not converge_flux and niter < 5:
            niter += 1
            converge_flux = True
            for iz in range(1,self.nz-1):
                for iy in range(self.ny):
                    for ix in range(self.nx):
                        # if (ix, iy, iz) is not a boundary condition node, i.e. not -1 (vac) and not -2 (ref)
                        imix = self.map['imix'][iz][iy][ix]
                        if imix >= 0:
                            xs = self.mix[imix]
                            az_over_v = 0.01/self.map['dz'][iz-1]
                            dzvac = 50*self.map['dz'][iz-1] + 0.71/xs.sigt[imix]
                            dxyvac = 0.5*self.pitch + 0.71/xs.sigt[imix]
                            Dimix = 1/(3*xs.sigt[imix])
                            for ig in reversed(range(self.ng)):
                                mlt = 0
                                dif = 0
                                # diffusion term: from bottom
                                imix_n =  self.map['imix'][iz-1][iy][ix]
                                if imix_n == -1:
                                    mlt += Dimix/dzvac * az_over_v
                                elif imix_n != -2:
                                    dz = 50*(self.map['dz'][iz-2] + self.map['dz'][iz-1])
                                    D = dz/(3*xs.sigt[imix_n]*self.map['dz'][iz-2] + 3*xs.sigt[imix]*self.map['dz'][iz-1])
                                    mlt += D/dz * az_over_v
                                    dif += D*self.flux[iz-1][iy][ix][ig]/dz * az_over_v
                                
                                # diffusion term: to top
                                imix_n =  self.map['imix'][iz+1][iy][ix]
                                if imix_n == -1:
                                    mlt += Dimix/dzvac * az_over_v
                                elif imix_n != -2:
                                    dz = 50*(self.map['dz'][iz-1] + self.map['dz'][iz])
                                    D = dz/(3*xs.sigt[imix]*self.map['dz'][iz-1] + 3*xs.sigt[imix_n]*self.map['dz'][iz])
                                    mlt += D/dz * az_over_v
                                    dif += D*self.flux[iz+1][iy][ix][ig]/dz * az_over_v
                                
                                # diffusion term: from west
                                imix_n =  self.map['imix'][iz][iy][ix-1]
                                if imix_n == -1:
                                    mlt += Dimix/dxyvac * self.aside_over_v
                                elif imix_n != -2:
                                    D = 2/(3*xs.sigt[imix] + 3*xs.sigt[imix_n])
                                    mlt += D/self.pitch * self.aside_over_v
                                    dif += D*self.flux[iz][iy][ix-1][ig]/self.pitch * self.aside_over_v
                                
                                # diffusion term: to east
                                imix_n =  self.map['imix'][iz][iy][ix+1]
                                if imix_n == -1:
                                    mlt += Dimix/dxyvac * self.aside_over_v
                                elif imix_n != -2:
                                    D = 2/(3*xs.sigt[imix] + 3*xs.sigt[imix_n])
                                    mlt += D/self.pitch * self.aside_over_v
                                    dif += D*self.flux[iz][iy][ix+1][ig]/self.pitch * self.aside_over_v
                                
                                if self.geom == 'square':
                                    # diffusion term: from north (square geometry)
                                    imix_n =  self.map['imix'][iz][iy-1][ix]
                                    if imix_n == -1:
                                        mlt += Dimix/dxyvac * self.aside_over_v
                                    elif imix_n != -2:
                                        D = 2/(3*xs.sigt[imix] + 3*xs.sigt[imix_n])
                                        mlt += D/self.pitch * self.aside_over_v
                                        dif += D*self.flux[iz][iy-1][ix][ig]/self.pitch * self.aside_over_v
                                    
                                    # diffusion term: from south (square geometry)
                                    imix_n =  self.map['imix'][iz][iy+1][ix]
                                    if imix_n == -1:
                                        mlt += Dimix/dxyvac * self.aside_over_v
                                    elif imix_n != -2:
                                        D = 2/(3*xs.sigt[imix] + 3*xs.sigt[imix_n])
                                        mlt += D/self.pitch * self.aside_over_v
                                        dif += D*self.flux[iz][iy+1][ix][ig]/self.pitch * self.aside_over_v
                                
                                elif self.geom == 'hex':
                                    # diffusion term: from north-west (hexagonal geometry)
                                    if iy % 2 == 0: # even
                                        imix_n =  self.map['imix'][iz][iy-1][ix]
                                    else: # odd
                                        imix_n =  self.map['imix'][iz][iy-1][ix-1]
                                    if imix_n == -1:
                                        mlt += Dimix/dxyvac * self.aside_over_v
                                    elif imix_n != -2:
                                        D = 2/(3*xs.sigt[imix] + 3*xs.sigt[imix_n])
                                        mlt += D/self.pitch * self.aside_over_v
                                        if iy % 2 == 0: # even
                                            dif += D*self.flux[iz][iy-1][ix][ig]/self.pitch * self.aside_over_v
                                        else: # odd
                                            dif += D*self.flux[iz][iy-1][ix-1][ig]/self.pitch * self.aside_over_v
                                
                                    # diffusion term: from north-east (hexagonal geometry)
                                    if iy % 2 == 0: # even
                                        imix_n =  self.map['imix'][iz][iy-1][ix+1]
                                    else: # odd
                                        imix_n =  self.map['imix'][iz][iy-1][ix]
                                    if imix_n == -1:
                                        mlt += Dimix/dxyvac * self.aside_over_v
                                    elif imix_n != -2:
                                        D = 2/(3*xs.sigt[imix] + 3*xs.sigt[imix_n])
                                        mlt += D/self.pitch * self.aside_over_v
                                        if iy % 2 == 0: # even
                                            dif += D*self.flux[iz][iy-1][ix+1][ig]/self.pitch * self.aside_over_v
                                        else: # odd
                                            dif += D*self.flux[iz][iy-1][ix][ig]/self.pitch * self.aside_over_v
                                
                                    # diffusion term: from south-west (hexagonal geometry)
                                    if iy % 2 == 0: # even
                                        imix_n =  self.map['imix'][iz][iy+1][ix]
                                    else: # odd
                                        imix_n =  self.map['imix'][iz][iy+1][ix-1]
                                    if imix_n == -1:
                                        mlt += Dimix/dxyvac * self.aside_over_v
                                    elif imix_n != -2:
                                        D = 2/(3*xs.sigt[imix] + 3*xs.sigt[imix_n])
                                        mlt += D/self.pitch * self.aside_over_v
                                        if iy % 2 == 0: # even
                                            dif += D*self.flux[iz][iy+1][ix][ig]/self.pitch * self.aside_over_v
                                        else: # odd
                                            dif += D*self.flux[iz][iy+1][ix-1][ig]/self.pitch * self.aside_over_v
                                
                                
                                    # diffusion term: from south-east (hexagonal geometry)
                                    if iy % 2 == 0: # even
                                        imix_n =  self.map['imix'][iz][iy+1][ix+1]
                                    else: # odd
                                        imix_n =  self.map['imix'][iz][iy+1][ix]
                                    if imix_n == -1:
                                        mlt += Dimix/dxyvac * self.aside_over_v
                                    elif imix_n != -2:
                                        D = 2/(3*xs.sigt[imix] + 3*xs.sigt[imix_n])
                                        mlt += D/self.pitch * self.aside_over_v
                                        if iy % 2 == 0: # even
                                            dif += D*self.flux[iz][iy+1][ix+1][ig]/self.pitch * self.aside_over_v
                                        else: # odd
                                            dif += D*self.flux[iz][iy+1][ix][ig]/self.pitch * self.aside_over_v
                                
                                # removal xs
                                sigr = xs.sigt[ig]
                                # scattering source
                                qs = 0
                                for indx in range(len(xs.sigs)):
                                    f = xs.sigs[indx][0][0]
                                    t = xs.sigs[indx][0][1]
                                    if f != ig and t == ig:
                                        qs += xs.sigs[indx][1] * self.flux[iz][iy][ix][f]
                                    if f == ig and t == ig:
                                        sigr -= xs.sigs[indx][1]
                                # n2n source
                                qn2n = 0
                                for indx in range(len(xs.sign2n)):
                                    f = xs.sign2n[indx][0][0]
                                    t = xs.sign2n[indx][0][1]
                                    if f != ig and t == ig:
                                        qn2n += 2*xs.sign2n[indx][1] * self.flux[iz][iy][ix][f]
                                    if f == ig and t == ig:
                                        sigr -= xs.sign2n[indx][1]
                                
                                mlt += sigr
                                
                                # fission source
                                qf = xs.chi[ig]*self.qf[iz][iy][ix]/self.k[-1]
                                
                                # neutron flux
                                flux = (dif + qs + qn2n + qf)/mlt
                                if converge_flux : converge_flux = abs(flux - self.flux[iz][iy][ix][ig]) < self.rtol*abs(flux) + self.atol
                                self.flux[iz][iy][ix][ig] = flux
                tac = time.time()
                print('{0:.3f}'.format(tac - reactor.tic), ' s | eigenvalue problem inner iteration: ', niter, ' | axial layer: ', iz)
                reactor.tic = tac

    #----------------------------------------------------------------------------------------------
    # calculate and return sparse matrix in plane iz for steady-state eigenvalue problem
    
    def build_matrix_eigenvalue_problem(self, iz):

        # diagonal matrix
        a1 = {'a':[], 'icol':[], 'ia1r':[]}
        irow, k = -1, -1
        for iy in range(self.ny):
            for ix in range(self.nx):
                # if (ix, iy, iz) is not a boundary condition node, i.e. not -1 (vac) and not -2 (ref)
                imix = self.map['imix'][iz][iy][ix]
                if imix >= 0:
                    xs = self.mix[imix]
                    ftsca_list = [s[0] for s in xs.sigs]
                    ftn2n_list = [s[0] for s in xs.sign2n]
                    for ig in range(self.ng):
                        irow += 1
                        a1['ia1r'].append(k+1)
                        for jg in range(self.ng):
                            if ig == jg:
                                # removal xs
                                sigr = xs.sigt[ig] - xs.sigs[ftsca_list.index((ig, ig))][1]
                                if (ig, ig) in ftn2n_list:
                                    sigr -= self.sign2n[ftn2n_list.index((ig, ig))][1]
                                k += 1
                                a1['a'].append(-sigr)
                                # this is a diagonal element
                                a1['icol'].append(irow)
                            else:
                                # scattering and n2n source
                                src = 0
                                if (jg, ig) in ftsca_list:
                                    src += xs.sigs[ftsca_list.index((jg, ig))][1]
                                if (jg, ig) in ftn2n_list:
                                    src += 2*xs.sign2n[ftn2n_list.index((jg, ig))][1]
                                if src != 0:
                                    k += 1
                                    a1['icol'].append(src)
                                    # this is an off-diagonal element
                                    a1['icol'].append(irow+jg-ig)
        return a1
