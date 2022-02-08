# -*- coding: utf-8 -*-
# The DiverseSelector library provides a set of tools to select molecule
# subset with maximum molecular diversity.
#
# Copyright (C) 2022 The QC-Devs Community
#
# This file is part of DiverseSelector.
#
# DiverseSelector is free software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License
# as published by the Free Software Foundation; either version 3
# of the License, or (at your option) any later version.
#
# DiverseSelector is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, see <http://www.gnu.org/licenses/>
#
# --

"""Feature generation module."""
import os
import sys
from typing import Any

import numpy as np
import pandas as pd
from mordred import Calculator, descriptors
from padelpy import from_sdf
from rdkit import Chem
from rdkit.Chem import AllChem, MACCSkeys, Descriptors
from rdkit.Chem import rdMHFPFingerprint

from .utils import ExplicitBitVect, PandasDataFrame, RDKitMol

__all__ = [
    "DescriptorGenerator",
    "FingerprintGenerator",
    "feature_filtering",
]

cwd = os.path.dirname(os.path.abspath(__file__))
sys.path.append(os.path.join(cwd, "padelpy"))


class DescriptorGenerator:
    def __init__(self,
                 mols: list,
                 desc_type: str = "mordred",
                 use_fragment: bool = True,
                 ipc_avg: bool = True,
                 ) -> None:
        """Molecular descriptor calculations.

        Parameters
        ----------
        mols : list
            A list of molecule RDKitMol objects.
        desc_type : str, optional
            Descriptor type name, which can be "mordred", "padel", "rdkit", "rdkit_frag",
            or the capitalized version. Default="mordred".
        use_fragment : bool, optional
            If True, the return value includes the fragment binary descriptors like "fr_XXX".
            Default=True.
        ipc_avg : bool, optional
            If True, the IPC descriptor calculates with avg=True option. Default=True

        """
        self.mols = mols
        self.desc_type = desc_type
        self.use_fragment = use_fragment
        self.ipc_avg = ipc_avg
        # self.__dict__.update(kwargs)

    def compute_descriptor(self,
                           **kwargs: Any,
                           ) -> PandasDataFrame:
        """Molecule descriptor generation."""
        if self.desc_type.lower() == "mordred":
            df_features = self.mordred_descriptors(self.mols)
        elif self.desc_type.lower() == "padel":
            df_features = self.padelpy_descriptors(self.mols)
        elif self.desc_type.lower() == "rdkit":
            df_features = self.rdkit_descriptors(self.mols,
                                                 use_fragment=self.use_fragment,
                                                 ipc_avg=self.ipc_avg,
                                                 *kwargs)
        elif self.desc_type.lower() == "rdkit_frag":
            df_features = self.rdkit_fragment_descriptors(self.mols)
        else:
            raise ValueError(f"Unknown descriptor type {self.desc_type}.")

        return df_features

    @staticmethod
    def mordred_descriptors(mols: list) -> PandasDataFrame:
        """Mordred molecular descriptor generation.

        Parameters
        ----------
        mols : list
            A list of molecule RDKitMol objects.

        Returns
        -------
        df_features: PandasDataFrame
            A `pandas.DataFrame` object with compute Mordred descriptors.

        """
        # if only compute 2D descriptors,
        # ignore_3D=True
        calc = Calculator(descriptors, ignore_3D=False)
        df_features = pd.DataFrame(calc.pandas(mols))

        return df_features

    @staticmethod
    def padelpy_descriptors(mols: list) -> PandasDataFrame:
        """PADEL molecular descriptor generation.

        Parameters
        ----------
        mols : list
            A list of molecule RDKitMol objects.

        Returns
        -------
        df_features: PandasDataFrame
            A `pandas.DataFrame` object with compute Mordred descriptors.

        """
        # if only compute 2D descriptors,
        # ignore_3D=True

        # save file temporarily
        writer = Chem.SDWriter("padelpy_out_tmp.sdf")
        for mol in mols:
            writer.write(mol)
        writer.close()

        desc = from_sdf(sdf_file="padelpy_out_tmp.sdf",
                        output_csv=None,
                        descriptors=True,
                        fingerprints=False,
                        timeout=None)
        df_features = pd.DataFrame(desc)

        # delete temporary file
        os.remove("padelpy_out_tmp.sdf")

        return df_features

    @staticmethod
    def rdkit_descriptors(mols: list,
                          use_fragment: bool = True,
                          ipc_avg: bool = True,
                          **kwargs,
                          ) -> PandasDataFrame:
        """RDKit molecular descriptor generation.

        Parameters
        ----------
        mols : list
            A list of molecule RDKitMol objects.
        use_fragment : bool, optional
            If True, the return value includes the fragment binary descriptors like "fr_XXX".
            Default=True.
        ipc_avg : bool, optional
            If True, the IPC descriptor calculates with avg=True option. Default=True
        **kwargs : Any, optional
            Other parameters that can be passed to `_rdkit_descriptors_low()`.

        Returns
        -------
        df_features: PandasDataFrame
            A `pandas.DataFrame` object with compute Mordred descriptors.

        """
        # parsing descriptor information
        desc_list = []
        descriptor_types = []
        for descriptor, function in Descriptors.descList:
            if use_fragment is False and descriptor.startswith("fr_"):
                continue
            descriptor_types.append(descriptor)
            desc_list.append((descriptor, function))

        # check initialization
        assert len(descriptor_types) == len(desc_list)

        arr_features = [_rdkit_descriptors_low(mol, desc_list=desc_list, ipc_avg=ipc_avg, *kwargs)
                        for mol in mols]
        df_features = pd.DataFrame(arr_features, columns=descriptor_types)

        return df_features

    @staticmethod
    def rdkit_fragment_descriptors(mols: list) -> PandasDataFrame:
        """RDKit fragment features.

        Parameters
        ----------
        mols : list
            A list of molecule RDKitMol objects.

        Returns
        -------
        df_features: PandasDataFrame
            A `pandas.DataFrame` object with compute Mordred descriptors.

        """
        # http://rdkit.org/docs/source/rdkit.Chem.Fragments.html
        # this implementation is taken from https://github.com/Ryan-Rhys/FlowMO/blob/
        # e221d989914f906501e1ad19cd3629d88eac1785/property_prediction/data_utils.py#L111
        fragments = {d[0]: d[1] for d in Descriptors.descList[115:]}
        frag_features = np.zeros((len(mols), len(fragments)))
        for idx, mol in enumerate(mols):
            features = [fragments[d](mol) for d in fragments]
            frag_features[idx, :] = features

        feature_names = [desc[0] for desc in Descriptors.descList[115:]]
        df_features = pd.DataFrame(data=frag_features, columns=feature_names)

        return df_features


# this part is modified from
# https://github.com/deepchem/deepchem/blob/master/deepchem/feat/molecule_featurizers/
# rdkit_descriptors.py#L11-L98
def _rdkit_descriptors_low(mol: RDKitMol,
                           desc_list: list,
                           ipc_avg: bool = True,
                           **kwargs) -> list:
    """Calculate RDKit descriptors.

    Parameters
    ----------
    mol : rdkit.Chem.rdchem.Mol
        RDKit Mol object.
    desc_list: list
        A list of tuples, which contain descriptor types and functions.
    use_fragment : bool, optional
        If True, the return value includes the fragment binary descriptors like "fr_XXX".
        Default=True.
    ipc_avg : bool, optional
        If True, the IPC descriptor calculates with avg=True option. Default=True

    Returns
    -------
    features : list
        1D list of RDKit descriptors for `mol`. The length is `len(descriptors)`.
    """
    if "mol" in kwargs:
        mol = kwargs.get("mol")
        raise DeprecationWarning(
            "Mol is being phased out as a parameter, please pass RDKit mol object instead.")

    features = []
    for desc_name, function in desc_list:
        if desc_name == "Ipc" and ipc_avg:
            feature = function(mol, avg=True)
        else:
            feature = function(mol)
        features.append(feature)
    # return np.asarray(features)
    return features


# feature selection
def feature_filtering():
    """Feature selection."""
    # todo: add feature selection for binary fingerprints
    pass


class FingerprintGenerator:
    def __init__(self,
                 mols: list,
                 fp_type: str = "SECFP",
                 n_bits: int = 2048,
                 radius: int = 3,
                 min_radius: int = 1,
                 random_seed: int = 12345,
                 rings: bool = True,
                 isomeric: bool = True,
                 kekulize: bool = False,
                 ) -> None:
        """Fingerprint generator"""
        self.mols = mols
        self.fp_type = fp_type
        self.n_bits = n_bits
        self.radius = radius
        self.min_radius = min_radius
        self.random_seed = random_seed
        self.rings = rings
        self.isomeric = isomeric
        self.kekulize = kekulize

        # molecule names
        mol_names = [Chem.MolToSmiles(mol) if mol.GetPropsAsDict().get("_Name") is None
                     else mol.GetProp("_Name") for mol in mols]
        self.mol_names = mol_names

    def compute_fingerprint(self) -> PandasDataFrame:
        """Compute fingerprints."""
        if self.fp_type.upper() in ["SECFP", "ECFP", "MORGAN", "RDKFINGERPRINT", "MACCSKEYS"]:
            fps = [self.rdkit_fingerprint_low(mol,
                                              fp_type=self.fp_type,
                                              n_bits=self.n_bits,
                                              radius=self.radius,
                                              min_radius=self.min_radius,
                                              random_seed=self.random_seed,
                                              rings=self.rings,
                                              isomeric=self.isomeric,
                                              kekulize=self.kekulize,
                                              ) for mol in self.mols]
        # todo: add support of e3fp

        # other cases
        else:
            raise ValueError(f"{self.desc_type} is not an supported fingerprint type.")

        df_fps = pd.DataFrame(np.array(fps), index=self.mol_names)

        return df_fps

    @staticmethod
    def rdkit_fingerprint_low(mol: RDKitMol,
                              fp_type: str = "SECFP",
                              n_bits: int = 2048,
                              radius: int = 3,
                              min_radius: int = 1,
                              random_seed: int = 12345,
                              rings: bool = True,
                              isomeric: bool = False,
                              kekulize: bool = False,
                              ) -> ExplicitBitVect:
        """
        Generate required molecular fingerprints.

        Parameters
        ----------
        mols : RDKitMol
            Molecule object.
        fp_type : str, optional
            Supported fingerprints: SECFP, ECFP, Morgan, RDKitFingerprint and MACCSkeys.
            Default="SECFP".
        n_bits : int, optional
            Number of bits of fingerprint. Default=2048.
        radius : int, optional
            The maximum radius of the substructure that is generated at each atom. Default=3.
        min_radius : int, optional
            The minimum radius that is used to extract n-grams.
        random_seed : int, optional
            The random seed number. Default=12345.
        rings : bool, optional
            Whether the rings (SSSR) are extracted from the molecule and added to the shingling.
            Default=True.
        isomeric : bool, optional
            Whether the SMILES added to the shingling are isomeric. Default=False.
        kekulize : bool, optional
            Whether the SMILES added to the shingling are kekulized. Default=True.

        Returns
        -------
        fp : ExplicitBitVect
            The computed molecular fingerprint.

        Notes
        -----
        fingerprint types:
        1. topological fingerprints: RDKFingerprint, Tanimoto, Dice, Cosine, Sokal, Russel,
        Kulczynski, McConnaughey, and Tversky
        2. MACCS keys:
        3. Atom pairs and topological torsions
        4. Morgan fingerprints (circular fingerprints): Morgan, ECFP, FCFP

        """
        # SECFP: SMILES extended connectivity fingerprint
        # https://jcheminf.biomedcentral.com/articles/10.1186/s13321-018-0321-8
        if fp_type == "SECFP":
            secfp_encoder = rdMHFPFingerprint.MHFPEncoder(n_bits, random_seed)
            fp = secfp_encoder.EncodeSECFPMol(mol,
                                              radius=radius, rings=rings, isomeric=isomeric,
                                              kekulize=kekulize, min_radius=min_radius)
        # ECFP
        # https://github.com/deepchem/deepchem/blob/1a2d2e9ff097fdbf58894d1f91359fe466c65810/deepchem/utils/rdkit_utils.py#L414
        # https://www.rdkit.org/docs/source/rdkit.Chem.rdMolDescriptors.html
        elif fp_type == "ECFP":
            # radius=3 --> ECFP6
            fp = AllChem.GetMorganFingerprintAsBitVect(mol=mol, radius=radius, nBits=n_bits,
                                                       useChirality=isomeric, useFeatures=False)
        elif fp_type == "Morgan":
            fp = AllChem.GetMorganFingerprintAsBitVect(mol=mol, radius=radius, nBits=n_bits,
                                                       useChirality=isomeric, useFeatures=True)
        # https://www.rdkit.org/docs/source/rdkit.Chem.rdmolops.html#rdkit.Chem.rdmolops.RDKFingerprint
        elif fp_type == "RDKFingerprint":
            fp = Chem.rdmolops.RDKFingerprint(mol=mol,
                                              minPath=1,
                                              # maxPath=mol.GetNumBonds(),
                                              maxPath=10,
                                              fpSize=n_bits,
                                              nBitsPerHash=2,
                                              useHs=True,
                                              tgtDensity=0,
                                              minSize=128,
                                              branchedPaths=True,
                                              useBondOrder=True,
                                              )
        # SMARTS-based implementation of the 166 public MACCS keys
        # https://www.rdkit.org/docs/GettingStartedInPython.html#fingerprinting-and-molecular-similarity
        elif fp_type == "MaCCSKeys":
            fp = MACCSkeys.GenMACCSKeys(mol)
        else:
            # todo: add more
            # https://github.com/keiserlab/e3fp
            # https://chemfp.readthedocs.io/en/latest/fp_types.html
            # https://xenonpy.readthedocs.io/en/stable/_modules/xenonpy/descriptor/fingerprint.html
            raise NotImplementedError("{} not implemented yet.".format(fp_type))

        return fp

    # todo: add support of e3fp fingerprint
    # @staticmethod
    # def e3fp_fingerprint(mols,
    #                      n_bits=2048,
    #                      radius=3,
    #                      isomeric=True,
    #                      ):
    #     """E3FP fingerprint."""
    #
    #     for mol in mols:
    #         mol_name = Chem.MolToSmiles(mol, isomericSmiles=True)
    #         try:
    #             mol.GetProp("_Name")
    #         except KeyError:
    #             mol.SetProp("_Name", mol_name)
    #
    #     # requires 3D molecule
    #     # cannot work with planer molecules
    #     # filter out molecules with only two atoms as /e3fp/fingerprint/fprinter.py line 547,
    #     # requires a 2-dimensional array
    #     # in __init__
    #     #     distance_matrix = array_ops.make_distance_matrix(atom_coords)
    #     mols_doable = [mol for mol in mols if mol.GetNumAtoms() != 2]
    #     mols_not_doable = [mol for mol in mols if mol.GetNumAtoms() == 2]
    #     # molecular name for diatomic molecule
    #     mol_names_doable = [mol.GetProp("_Name") for mol in mols_doable]
    #     # molecular name for molecules with one atom or more than two atoms
    #     mol_names_two_atoms = [mol.GetProp("_Name") for mol in mols_not_doable]
    #
    #     # e3fp configuration
    #     # https://e3fp.readthedocs.io/en/latest/usage/config.html#configuration
    #     # https://e3fp.readthedocs.io/en/latest/_modules/e3fp/fingerprint/generate.html
    #     fprint_params = {"bits": n_bits,
    #                      "radius_multiplier": radius,
    #                      "first": 1,
    #                      "stereo": isomeric,
    #                      "counts": False,
    #                      # Use the atom invariants used by RDKit for its Morgan fingerprint
    #                      "rdkit_invariants": False,
    #                      "level": -1,
    #                      "include_disconnected": False,
    #                      "remove_duplicate_substructs": True,
    #                      "exclude_floating": True,
    #                      "overwrite": True,
    #                      }
    #
    #     # generate e3fp fingerprint from SDF files
    #     # fps = map(fprints_from_mol, mols, fprint_params)
    #     fps = [fprints_from_mol(mol, fprint_params=fprint_params) for mol in mols_doable]
    #     fps_folded = np.array([fp[0].fold().to_vector(sparse=False, dtype=int) for fp in fps])
    #
    #     # convert to pandas.DataFrame
    #     df_e3fp = pd.DataFrame(data=fps_folded, index=mol_names_doable)
    #
    #     return df_e3fp, mol_names_doable, mol_names_two_atoms