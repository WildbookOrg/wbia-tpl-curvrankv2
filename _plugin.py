from __future__ import absolute_import, division, print_function
from ibeis.control import controller_inject  # NOQA
from os.path import abspath, join, exists
import ibeis_curvrank.functional as F
import numpy as np
import utool as ut


# We want to register the depc plugin functions as well, so import it here for IBEIS
import ibeis_curvrank._plugin_depc  # NOQA
from ibeis_curvrank._plugin_depc import DEFAULT_SCALES


_, register_ibs_method = controller_inject.make_ibs_register_decorator(__name__)
register_api = controller_inject.get_ibeis_flask_api(__name__)


USE_DEPC = True


URL_DICT = {
    'localization': 'https://lev.cs.rpi.edu/public/models/curvrank.localization.weights.pkl',
    'segmentation': 'https://lev.cs.rpi.edu/public/models/curvrank.segmentation.weights.pkl',
}


def _assert_hashes(data, hash_list, tag='data'):
    data_hash = ut.hash_data(data)
    print('ut.hash_data(%s) = %r' % (tag, data_hash, ))
    assert data_hash in hash_list


@register_ibs_method
def ibeis_plugin_curvrank_scores(ibs, db_aid_list, qr_aid_list, lnbnn_k=2, config={},
                                 verbose=False, use_names=True, use_depc=USE_DEPC):
    r"""
    CurvRank Example

    Args:
        ibs       (IBEISController): IBEIS controller object
        lnbnn_k   (int): list of image rowids (aids)

    Returns:
        score_dict

    CommandLine:
        python -m ibeis_curvrank._plugin --test-ibeis_plugin_curvrank_scores

    Example1:
        >>> # ENABLE_DOCTEST
        >>> from ibeis_curvrank._plugin import *  # NOQA
        >>> import ibeis
        >>> from ibeis.init import sysres
        >>> dbdir = sysres.ensure_testdb_curvrank()
        >>> ibs = ibeis.opendb(dbdir=dbdir)
        >>> db_imageset_rowid = ibs.get_imageset_imgsetids_from_text('database')
        >>> db_aid_list = ibs.get_imageset_aids(db_imageset_rowid)
        >>> qr_imageset_rowid = ibs.get_imageset_imgsetids_from_text('query')
        >>> qr_aid_list = ibs.get_imageset_aids(qr_imageset_rowid)
        >>> score_dict = ibs.ibeis_plugin_curvrank_scores(db_aid_list, qr_aid_list, use_depc=False)
        >>> for key in score_dict:
        >>>     score_dict[key] = round(score_dict[key], 8)
        >>> result = score_dict
        >>> print(result)
        {1: -31.3653052, 2: -3.09841482, 3: -4.30560276}
    """
    cache_path = abspath(join(ibs.get_cachedir(), 'curvrank'))
    ut.ensuredir(cache_path)

    if verbose:
        print('Loading database data...')

    values = ibs.ibeis_plugin_curvrank_pipeline(aid_list=db_aid_list, config=config,
                                                verbose=verbose, use_depc=use_depc)
    db_lnbnn_data, _ = values

    if verbose:
        print('Loading query data...')

    values = ibs.ibeis_plugin_curvrank_pipeline(aid_list=qr_aid_list, config=config,
                                                verbose=verbose, use_depc=use_depc)
    qr_lnbnn_data, _ = values

    if verbose:
        print('Loading index for scales...')

    db_annot_uuid_list = ibs.get_annot_uuids(db_aid_list)
    index_hash = ut.hash_data(db_annot_uuid_list)
    index_directory = 'index_%s_aids_%d' % (index_hash, len(db_aid_list), )
    index_path = join(cache_path, index_directory)
    ut.ensuredir(index_path)

    # Build (and cache to disk) LNBNN indexes
    index_filepath_dict = {}
    for scale in db_lnbnn_data:
        index_filepath = join(index_path, '%s.ann' % scale)
        if not exists(index_filepath):
            descriptors, aids = db_lnbnn_data[scale]
            F.build_lnbnn_index(descriptors, index_filepath)
        index_filepath_dict[scale] = index_filepath

    if verbose:
        print('Aggregating scores...')

    # Run LNBNN identification for each scale independently and aggregate
    score_dict = {}
    for scale in index_filepath_dict:
        assert scale in index_filepath_dict
        assert scale in db_lnbnn_data
        assert scale in qr_lnbnn_data

        index_filepath = index_filepath_dict[scale]
        db_descriptors, db_aids = db_lnbnn_data[scale]
        qr_descriptors, qr_aids = qr_lnbnn_data[scale]

        if use_names:
            db_rowids = ibs.get_annot_nids(db_aids)
        else:
            db_rowids = db_aids

        score_dict_ = F.lnbnn_identify(index_filepath, lnbnn_k, qr_descriptors, db_rowids)
        for rowid in score_dict_:
            if rowid not in score_dict:
                score_dict[rowid] = 0.0
            score_dict[rowid] += score_dict_[rowid]

    return score_dict


@register_ibs_method
def ibeis_plugin_curvrank_preprocessing(ibs, aid_list, width=256, height=256, **kwargs):
    r"""
    Pre-process images for CurvRank

    Args:
        ibs       (IBEISController): IBEIS controller object
        aid_list  (list of int): list of image rowids (aids)

    Returns:
        resized_images
        resized_masks
        pre_transforms

    CommandLine:
        python -m ibeis_curvrank._plugin --test-ibeis_plugin_curvrank_preprocessing

    Example:
        >>> # ENABLE_DOCTEST
        >>> from ibeis_curvrank._plugin import *  # NOQA
        >>> import ibeis
        >>> from ibeis.init import sysres
        >>> dbdir = sysres.ensure_testdb_curvrank()
        >>> ibs = ibeis.opendb(dbdir=dbdir)
        >>> aid_list = ibs.get_image_aids(1)
        >>> values = ibs.ibeis_plugin_curvrank_preprocessing(aid_list)
        >>> resized_images, resized_masks, pre_transforms = values
        >>> resized_image = resized_images[0]
        >>> resized_mask  = resized_masks[0]
        >>> pre_transform = pre_transforms[0]
        >>> assert ut.hash_data(resized_image) in ['inxtvdeyxibloygwuyhxzpnevpkoenec']
        >>> assert ut.hash_data(resized_mask)  in ['mnhartnytowmmhskblocubqmzhbofynr']
        >>> result = pre_transform
        >>> print(result)
        [[ 0.36571429  0.          0.        ]
         [ 0.          0.36571429 38.        ]
         [ 0.          0.          1.        ]]
    """
    image_list = ibs.get_annot_chips(aid_list)

    viewpoint_list = ibs.get_annot_viewpoints(aid_list)
    flip_list = [viewpoint == 'right' for viewpoint in viewpoint_list]

    resized_images, resized_masks, pre_transforms = [], [], []
    for image, flip in zip(image_list, flip_list):
        vals = F.preprocess_image(image, flip, height, width)

        resized_image, resized_mask, pre_transform = vals
        resized_images.append(resized_image)
        resized_masks.append(resized_mask)
        pre_transforms.append(pre_transform)

    return resized_images, resized_masks, pre_transforms


@register_ibs_method
def ibeis_plugin_curvrank_localization(ibs, resized_images, resized_masks,
                                       width=256, height=256,
                                       model_tag='localization', **kwargs):
    r"""
    Localize images for CurvRank

    Args:
        ibs       (IBEISController): IBEIS controller object
        model_tag  (string): Key to URL_DICT entry for this model
        resized_images (list of np.ndarray): widthXheightX3 color channels
        resized_masks (list of np.ndarray): heightXwidth greyscale images

    Returns:
        localized_images
        localized_masks
        loc_transforms

    CommandLine:
        python -m ibeis_curvrank._plugin --test-ibeis_plugin_curvrank_localization

    Example:
        >>> # ENABLE_DOCTEST
        >>> from ibeis_curvrank._plugin import *  # NOQA
        >>> import ibeis
        >>> from ibeis.init import sysres
        >>> import numpy as np
        >>> dbdir = sysres.ensure_testdb_curvrank()
        >>> ibs = ibeis.opendb(dbdir=dbdir)
        >>> aid_list = ibs.get_image_aids(1)
        >>> values = ibs.ibeis_plugin_curvrank_preprocessing(aid_list)
        >>> resized_images, resized_masks, pre_transforms = values
        >>> values = ibs.ibeis_plugin_curvrank_localization(resized_images, resized_masks)
        >>> localized_images, localized_masks, loc_transforms = values
        >>> localized_image = localized_images[0]
        >>> localized_mask  = localized_masks[0]
        >>> loc_transform = loc_transforms[0]
        >>> # localized_image appears to differ very slightly in ubuntu vs. mac. Hashes below for each respectively.
        >>> #TODO verify that mac/ubuntu values are consistent on those OSes
        >>> assert ut.hash_data(localized_image) in ['igxwfzwvpbqpfriihmdsyaoksqbzviey']
        >>> assert ut.hash_data(localized_mask)  in ['whrbbdtqbmpyjskvvpvblehfiofdgsli']
        >>> # for above reasons, some voodoo to compare loc_transform
        >>> loc_transform_ubuntu = np.array([[ 6.42954651e-01,  1.20030158e-01, -1.06427952e-01],
                                             [-1.19038359e-01,  6.43158788e-01, -1.27811638e-04],
                                             [ 0.00000000e+00,  0.00000000e+00,  1.00000000e+00]])
        >>> assert np.all(np.abs(loc_transform - loc_transform_ubuntu) < 1e-6)
    """
    from ibeis_curvrank import localization, model, theano_funcs

    model_url = URL_DICT.get(model_tag, None)
    assert model_url is not None
    weight_filepath = ut.grab_file_url(model_url, appname='ibeis_curvrank', check_hash=True)

    # Make sure resized images all have the same shape
    layers = localization.build_model((None, 3, height, width))
    model.load_weights(
        [
            layers['trans'],
            layers['loc']
        ],
        weight_filepath
    )
    localization_func = theano_funcs.create_localization_infer_func(layers)
    values = F.localize(resized_images, resized_masks, height, width, localization_func)
    localized_images, localized_masks, loc_transforms = values

    return localized_images, localized_masks, loc_transforms


@register_ibs_method
def ibeis_plugin_curvrank_refinement(ibs, aid_list, pre_transforms,
                                     loc_transforms, width=256, height=256,
                                     scale=4, **kwargs):
    r"""
    Refine localizations for CurvRank

    Args:
        ibs       (IBEISController): IBEIS controller object
        aid_list  (list of int): list of image rowids (aids)
        pre_transforms (list of np.ndarray):
        loc_transforms (list of np.ndarray):
        scale (int): how many scales to perform the refinement (default to 4).

    Returns:
        refined_localizations
        refined_masks

    CommandLine:
        python -m ibeis_curvrank._plugin --test-ibeis_plugin_curvrank_refinement

    Example:
        >>> # ENABLE_DOCTEST
        >>> from ibeis_curvrank._plugin import *  # NOQA
        >>> import ibeis
        >>> from ibeis.init import sysres
        >>> dbdir = sysres.ensure_testdb_curvrank()
        >>> ibs = ibeis.opendb(dbdir=dbdir)
        >>> aid_list = ibs.get_image_aids(1)
        >>> values = ibs.ibeis_plugin_curvrank_preprocessing(aid_list)
        >>> resized_images, resized_masks, pre_transforms = values
        >>> values = ibs.ibeis_plugin_curvrank_localization(resized_images, resized_masks)
        >>> localized_images, localized_masks, loc_transforms = values
        >>> values = ibs.ibeis_plugin_curvrank_refinement(aid_list, pre_transforms, loc_transforms)
        >>> refined_localizations, refined_masks = values
        >>> refined_localization = refined_localizations[0]
        >>> refined_mask         = refined_masks[0]
        >>> #TODO verify that mac/ubuntu values are consistent on those OSes
        >>> assert ut.hash_data(refined_localization) in ['nxhumkmybgbjdjcffuneozzmptvivvlh']
        >>> assert ut.hash_data(refined_mask)         in ['bwuzcdgbfyqhzgdthazfgegbzeykvbnt']
    """
    image_list = ibs.get_annot_chips(aid_list)

    viewpoint_list = ibs.get_annot_viewpoints(aid_list)
    flip_list = [viewpoint == 'right' for viewpoint in viewpoint_list]

    refined_localizations, refined_masks = [], []
    zipped = zip(image_list, flip_list, pre_transforms, loc_transforms)
    for image, flip, pre_transform, loc_transform in zipped:
        refined_localization, refined_mask = F.refine_localization(
            image, flip, pre_transform, loc_transform,
            scale, height, width
        )
        refined_localizations.append(refined_localization)
        refined_masks.append(refined_mask)

    return refined_localizations, refined_masks


@register_ibs_method
def ibeis_plugin_curvrank_segmentation(ibs, refined_localizations, refined_masks,
                                       width=256, height=256, scale=4,
                                       model_tag='segmentation', **kwargs):
    r"""
    Localize images for CurvRank

    Args:
        ibs       (IBEISController): IBEIS controller object
        refined_localizations: output of ibeis_plugin_curvrank_refinement
        refined_masks: output of ibeis_plugin_curvrank_refinement
        model_tag  (string): Key to URL_DICT entry for this model
        scale (int): how many scales to perform the refinement (default to 4).

    Returns:
        segmentations
        refined_segmentations

    CommandLine:
        python -m ibeis_curvrank._plugin --test-ibeis_plugin_curvrank_segmentation

    Example:
        >>> # ENABLE_DOCTEST
        >>> from ibeis_curvrank._plugin import *  # NOQA
        >>> import ibeis
        >>> from ibeis.init import sysres
        >>> dbdir = sysres.ensure_testdb_curvrank()
        >>> ibs = ibeis.opendb(dbdir=dbdir)
        >>> aid_list = ibs.get_image_aids(1)
        >>> values = ibs.ibeis_plugin_curvrank_preprocessing(aid_list)
        >>> resized_images, resized_masks, pre_transforms = values
        >>> values = ibs.ibeis_plugin_curvrank_localization(resized_images, resized_masks)
        >>> localized_images, localized_masks, loc_transforms = values
        >>> values = ibs.ibeis_plugin_curvrank_refinement(aid_list, pre_transforms, loc_transforms)
        >>> refined_localizations, refined_masks = values
        >>> values = ibs.ibeis_plugin_curvrank_segmentation(refined_localizations, refined_masks)
        >>> segmentations, refined_segmentations = values
        >>> segmentation = segmentations[0]
        >>> refined_segmentation = refined_segmentations[0]
        >>> assert ut.hash_data(segmentation)         in ['tcfybjuqszadvmfetzxivcvihfkudvqh']
        >>> assert ut.hash_data(refined_segmentation) in ['snjswkyqprmhmpefiiiapdsytubfvcwo']
    """
    from ibeis_curvrank import segmentation, model, theano_funcs

    model_url = URL_DICT.get(model_tag, None)
    assert model_url is not None
    weight_filepath = ut.grab_file_url(model_url, appname='ibeis_curvrank', check_hash=True)

    segmentation_layers = segmentation.build_model_batchnorm_full((None, 3, height, width))

    # I am not sure these are the correct args to load_weights
    model.load_weights(segmentation_layers['seg_out'], weight_filepath)
    segmentation_func = theano_funcs.create_segmentation_func(segmentation_layers)
    values = F.segment_contour(refined_localizations, refined_masks, scale,
                               height, width, segmentation_func)
    segmentations, refined_segmentations = values
    return segmentations, refined_segmentations


@register_ibs_method
def ibeis_plugin_curvrank_keypoints(ibs, segmentations, localized_masks, **kwargs):
    r"""
    Args:
        ibs       (IBEISController): IBEIS controller object
        segmentations: output of ibeis_plugin_curvrank_segmentation
        refined_masks: output of ibeis_plugin_curvrank_refinement

    Returns:
        success_list: bool list
        starts: list of keypoint starts
        ends: list of keypoint ends

    CommandLine:
        python -m ibeis_curvrank._plugin --test-ibeis_plugin_curvrank_keypoints

    Example:
        >>> # ENABLE_DOCTEST
        >>> from ibeis_curvrank._plugin import *  # NOQA
        >>> import ibeis
        >>> from ibeis.init import sysres
        >>> dbdir = sysres.ensure_testdb_curvrank()
        >>> ibs = ibeis.opendb(dbdir=dbdir)
        >>> aid_list = ibs.get_image_aids(1)
        >>> values = ibs.ibeis_plugin_curvrank_preprocessing(aid_list)
        >>> resized_images, resized_masks, pre_transforms = values
        >>> values = ibs.ibeis_plugin_curvrank_localization(resized_images, resized_masks)
        >>> localized_images, localized_masks, loc_transforms = values
        >>> values = ibs.ibeis_plugin_curvrank_refinement(aid_list, pre_transforms, loc_transforms)
        >>> refined_localizations, refined_masks = values
        >>> values = ibs.ibeis_plugin_curvrank_segmentation(refined_localizations, refined_masks)
        >>> segmentations, refined_segmentations = values
        >>> values = ibs.ibeis_plugin_curvrank_keypoints(segmentations, localized_masks)
        >>> success_list, starts, ends = values
        >>> start = tuple(starts[0])
        >>> end = tuple(ends[0])
        >>> assert success_list == [True]
        >>> assert start == (203, 3)
        >>> assert end   == (198, 252)
    """
    from ibeis_curvrank.dorsal_utils import find_dorsal_keypoints

    starts, ends, success_list = [], [], []

    for segmentation, localized_mask in zip(segmentations, localized_masks):
        start, end = F.find_keypoints(
            find_dorsal_keypoints,
            segmentation,
            localized_mask
        )

        success = start is not None and end is not None

        success_list.append(success)
        starts.append(start)
        ends.append(end)
    return success_list, starts, ends


@register_ibs_method
def ibeis_plugin_curvrank_outline(ibs, success_list, starts, ends,
                                  refined_localizations, refined_masks,
                                  refined_segmentations, scale=4,
                                  allow_diagonal=False, **kwargs):
    r"""
    Args:
        ibs       (IBEISController): IBEIS controller object
        success_list: output of ibeis_plugin_curvrank_keypoints
        starts: output of ibeis_plugin_curvrank_keypoints
        ends: output of ibeis_plugin_curvrank_keypoints
        refined_localizations: output of ibeis_plugin_curvrank_refinement
        refined_masks: output of ibeis_plugin_curvrank_refinement
        refined_segmentations: output of ibeis_plugin_curvrank_refinement
    Returns:
        success_list
        outlines

    CommandLine:
        python -m ibeis_curvrank._plugin --test-ibeis_plugin_curvrank_outline

    Example:
        >>> # ENABLE_DOCTEST
        >>> from ibeis_curvrank._plugin import *  # NOQA
        >>> import ibeis
        >>> from ibeis.init import sysres
        >>> dbdir = sysres.ensure_testdb_curvrank()
        >>> ibs = ibeis.opendb(dbdir=dbdir)
        >>> aid_list = ibs.get_image_aids(1)
        >>> values = ibs.ibeis_plugin_curvrank_preprocessing(aid_list)
        >>> resized_images, resized_masks, pre_transforms = values
        >>> values = ibs.ibeis_plugin_curvrank_localization(resized_images, resized_masks)
        >>> localized_images, localized_masks, loc_transforms = values
        >>> values = ibs.ibeis_plugin_curvrank_refinement(aid_list, pre_transforms, loc_transforms)
        >>> refined_localizations, refined_masks = values
        >>> values = ibs.ibeis_plugin_curvrank_segmentation(refined_localizations, refined_masks)
        >>> segmentations, refined_segmentations = values
        >>> values = ibs.ibeis_plugin_curvrank_keypoints(segmentations, localized_masks)
        >>> success_list, starts, ends = values
        >>> args = success_list, starts, ends, refined_localizations, refined_masks, refined_segmentations
        >>> success_list, outlines = ibs.ibeis_plugin_curvrank_outline(*args)
        >>> outline = outlines[0]
        >>> assert success_list == [True]
        >>> assert ut.hash_data(outline) in ['lyrkwgzncvjpjvovikkvspdkecardwyz']
    """
    from ibeis_curvrank.dorsal_utils import dorsal_cost_func

    success_list_ = []
    outlines = []
    zipped = zip(success_list, starts, ends, refined_localizations,
                 refined_masks, refined_segmentations)
    for value in zipped:
        success, start, end, refined_loc, refined_mask, refined_seg = value
        success_ = success
        if success:
            outline = F.extract_outline(
                refined_loc, refined_mask, refined_seg, scale, start, end,
                dorsal_cost_func, allow_diagonal)
            if outline is None:
                success_ = False
        else:
            outline = None

        success_list_.append(success_)
        outlines.append(outline)

    return success_list_, outlines


@register_ibs_method
def ibeis_plugin_curvrank_trailing_edges(ibs, success_list, outlines, **kwargs):
    r"""
    Args:
        ibs       (IBEISController): IBEIS controller object
        success_list: output of ibeis_plugin_curvrank_outline
        outlines (list of np.ndarray): output of ibeis_plugin_curvrank_outline

    Returns:
        success_list_
        trailing_edges

    CommandLine:
        python -m ibeis_curvrank._plugin --test-ibeis_plugin_curvrank_trailing_edges

    Example:
        >>> # ENABLE_DOCTEST
        >>> from ibeis_curvrank._plugin import *  # NOQA
        >>> import ibeis
        >>> from ibeis.init import sysres
        >>> dbdir = sysres.ensure_testdb_curvrank()
        >>> ibs = ibeis.opendb(dbdir=dbdir)
        >>> aid_list = ibs.get_image_aids(1)
        >>> values = ibs.ibeis_plugin_curvrank_preprocessing(aid_list)
        >>> resized_images, resized_masks, pre_transforms = values
        >>> values = ibs.ibeis_plugin_curvrank_localization(resized_images, resized_masks)
        >>> localized_images, localized_masks, loc_transforms = values
        >>> values = ibs.ibeis_plugin_curvrank_refinement(aid_list, pre_transforms, loc_transforms)
        >>> refined_localizations, refined_masks = values
        >>> values = ibs.ibeis_plugin_curvrank_segmentation(refined_localizations, refined_masks)
        >>> segmentations, refined_segmentations = values
        >>> values = ibs.ibeis_plugin_curvrank_keypoints(segmentations, localized_masks)
        >>> success_list, starts, ends = values
        >>> args = success_list, starts, ends, refined_localizations, refined_masks, refined_segmentations
        >>> success_list, outlines = ibs.ibeis_plugin_curvrank_outline(*args)
        >>> values = ibs.ibeis_plugin_curvrank_trailing_edges(success_list, outlines)
        >>> success_list, trailing_edges = values
        >>> trailing_edge = trailing_edges[0]
        >>> assert success_list == [True]
        >>> assert ut.hash_data(trailing_edge) in ['wiabdtkbaqjuvszkyvyjnpomrivyadaa']
    """
    from ibeis_curvrank.dorsal_utils import separate_leading_trailing_edges

    success_list_ = []
    trailing_edges = []
    for success, outline in zip(success_list, outlines):
        success_ = success
        if success:
            values = F.separate_edges(separate_leading_trailing_edges, outline)
            _, trailing_edge = values

            if trailing_edge is None:
                success_ = False
        else:
            trailing_edge = None

        success_list_.append(success_)
        trailing_edges.append(trailing_edge)

    return success_list_, trailing_edges


@register_ibs_method
def ibeis_plugin_curvrank_curvatures(ibs, success_list, trailing_edges,
                                     scales=DEFAULT_SCALES, transpose_dims=False,
                                     **kwargs):
    r"""
    Args:
        ibs       (IBEISController): IBEIS controller object
        success_list: output of ibeis_plugin_curvrank_outline
        outlines (list of np.ndarray): output of ibeis_plugin_curvrank_outline

    Returns:
        success_list_
        curvatures

    CommandLine:
        python -m ibeis_curvrank._plugin --test-ibeis_plugin_curvrank_curvatures

    Example:
        >>> # ENABLE_DOCTEST
        >>> from ibeis_curvrank._plugin import *  # NOQA
        >>> import ibeis
        >>> from ibeis.init import sysres
        >>> dbdir = sysres.ensure_testdb_curvrank()
        >>> ibs = ibeis.opendb(dbdir=dbdir)
        >>> aid_list = ibs.get_image_aids(1)
        >>> values = ibs.ibeis_plugin_curvrank_preprocessing(aid_list)
        >>> resized_images, resized_masks, pre_transforms = values
        >>> values = ibs.ibeis_plugin_curvrank_localization(resized_images, resized_masks)
        >>> localized_images, localized_masks, loc_transforms = values
        >>> values = ibs.ibeis_plugin_curvrank_refinement(aid_list, pre_transforms, loc_transforms)
        >>> refined_localizations, refined_masks = values
        >>> values = ibs.ibeis_plugin_curvrank_segmentation(refined_localizations, refined_masks)
        >>> segmentations, refined_segmentations = values
        >>> values = ibs.ibeis_plugin_curvrank_keypoints(segmentations, localized_masks)
        >>> success_list, starts, ends = values
        >>> args = success_list, starts, ends, refined_localizations, refined_masks, refined_segmentations
        >>> success_list, outlines = ibs.ibeis_plugin_curvrank_outline(*args)
        >>> values = ibs.ibeis_plugin_curvrank_trailing_edges(success_list, outlines)
        >>> success_list, trailing_edges = values
        >>> values = ibs.ibeis_plugin_curvrank_curvatures(success_list, trailing_edges)
        >>> success_list, curvatures = values
        >>> curvature = curvatures[0]
        >>> assert success_list == [True]
        >>> assert ut.hash_data(curvature) in ['yeyykrdbfxqyrbdumvpkvatjoddavdgn']
    """
    success_list_ = []
    curvatures = []
    for success, trailing_edge in zip(success_list, trailing_edges):
        success_ = success
        if success:
            curvature = F.compute_curvature(trailing_edge, scales, transpose_dims)

            if curvature is None:
                success_ = False
        else:
            curvature = None

        success_list_.append(success_)
        curvatures.append(curvature)

    return success_list_, curvatures


@register_ibs_method
def ibeis_plugin_curvrank_curvature_descriptors(ibs, success_list, curvatures,
                                                curv_length=1024, scales=DEFAULT_SCALES,
                                                num_keypoints=32, uniform=False,
                                                feat_dim=32, **kwargs):
    r"""
    Args:
        ibs       (IBEISController): IBEIS controller object
        success_list: output of ibeis_plugin_curvrank_outline
        outlines (list of np.ndarray): output of ibeis_plugin_curvrank_outline

    Returns:
        success_list_
        curvature_descriptors

    CommandLine:
        python -m ibeis_curvrank._plugin --test-ibeis_plugin_curvrank_curvature_descriptors

    Example:
        >>> # ENABLE_DOCTEST
        >>> from ibeis_curvrank._plugin import *  # NOQA
        >>> import ibeis
        >>> from ibeis.init import sysres
        >>> dbdir = sysres.ensure_testdb_curvrank()
        >>> ibs = ibeis.opendb(dbdir=dbdir)
        >>> aid_list = ibs.get_image_aids(1)
        >>> values = ibs.ibeis_plugin_curvrank_preprocessing(aid_list)
        >>> resized_images, resized_masks, pre_transforms = values
        >>> values = ibs.ibeis_plugin_curvrank_localization(resized_images, resized_masks)
        >>> localized_images, localized_masks, loc_transforms = values
        >>> values = ibs.ibeis_plugin_curvrank_refinement(aid_list, pre_transforms, loc_transforms)
        >>> refined_localizations, refined_masks = values
        >>> values = ibs.ibeis_plugin_curvrank_segmentation(refined_localizations, refined_masks)
        >>> segmentations, refined_segmentations = values
        >>> values = ibs.ibeis_plugin_curvrank_keypoints(segmentations, localized_masks)
        >>> success_list, starts, ends = values
        >>> args = success_list, starts, ends, refined_localizations, refined_masks, refined_segmentations
        >>> success_list, outlines = ibs.ibeis_plugin_curvrank_outline(*args)
        >>> values = ibs.ibeis_plugin_curvrank_trailing_edges(success_list, outlines)
        >>> success_list, trailing_edges = values
        >>> values = ibs.ibeis_plugin_curvrank_curvatures(success_list, trailing_edges)
        >>> success_list, curvatures = values
        >>> values = ibs.ibeis_plugin_curvrank_curvature_descriptors(success_list, curvatures)
        >>> success_list, curvature_descriptor_dicts = values
        >>> curvature_descriptor_dict = curvature_descriptor_dicts[0]
        >>> assert success_list == [True]
        >>> hash_list = [
        >>>     ut.hash_data(curvature_descriptor_dict[scale])
        >>>     for scale in sorted(list(curvature_descriptor_dict.keys()))
        >>> ]
        >>> assert ut.hash_data(hash_list) in ['mkhgqrrkhisuaenxkuxgbbcqpdfpoofp']
    """
    scale_str_list = [
        '%0.04f' % (scale, )
        for scale in scales
    ]
    success_list_ = []
    curvature_descriptor_dicts = []
    for success, curvature in zip(success_list, curvatures):
        success_ = success
        if success:
            curvature_descriptor_list = F.compute_curvature_descriptors(
                curvature,
                curv_length,
                scales,
                num_keypoints,
                uniform,
                feat_dim
            )

            if curvature_descriptor_list is None:
                success_ = False
        else:
            curvature_descriptor_list = None

        curvature_descriptor_dict = None
        if curvature_descriptor_list is not None:
            curvature_descriptor_dict = {
                scale_str: curvature_descriptor
                for scale_str, curvature_descriptor in zip(scale_str_list, curvature_descriptor_list)
            }

        success_list_.append(success_)
        curvature_descriptor_dicts.append(curvature_descriptor_dict)

    return success_list_, curvature_descriptor_dicts


@register_ibs_method
def ibeis_plugin_curvrank_pipeline_compute(ibs, aid_list, config={}):
    r"""
    Args:
        ibs       (IBEISController): IBEIS controller object
        success_list: output of ibeis_plugin_curvrank_outline
        outlines (list of np.ndarray): output of ibeis_plugin_curvrank_outline

    Returns:
        success_list_
        curvature_descriptors

    CommandLine:
        python -m ibeis_curvrank._plugin --test-ibeis_plugin_curvrank_pipeline_compute

    Example:
        >>> # ENABLE_DOCTEST
        >>> from ibeis_curvrank._plugin import *  # NOQA
        >>> import ibeis
        >>> from ibeis.init import sysres
        >>> dbdir = sysres.ensure_testdb_curvrank()
        >>> ibs = ibeis.opendb(dbdir=dbdir)
        >>> aid_list = ibs.get_image_aids(1)
        >>> values = ibs.ibeis_plugin_curvrank_pipeline_compute(aid_list)
        >>> success_list, curvature_descriptor_dicts = values
        >>> curvature_descriptor_dict = curvature_descriptor_dicts[0]
        >>> assert success_list == [True]
        >>> hash_list = [
        >>>     ut.hash_data(curvature_descriptor_dict[scale])
        >>>     for scale in sorted(list(curvature_descriptor_dict.keys()))
        >>> ]
        >>> assert ut.hash_data(hash_list) in ['mkhgqrrkhisuaenxkuxgbbcqpdfpoofp']
    """
    values = ibs.ibeis_plugin_curvrank_preprocessing(aid_list, **config)
    resized_images, resized_masks, pre_transforms = values

    values = ibs.ibeis_plugin_curvrank_localization(resized_images, resized_masks, **config)
    localized_images, localized_masks, loc_transforms = values

    values = ibs.ibeis_plugin_curvrank_refinement(aid_list, pre_transforms, loc_transforms, **config)
    refined_localizations, refined_masks = values

    values = ibs.ibeis_plugin_curvrank_segmentation(refined_localizations, refined_masks, **config)
    segmentations, refined_segmentations = values

    values = ibs.ibeis_plugin_curvrank_keypoints(segmentations, localized_masks, **config)
    success, starts, ends = values

    args = success, starts, ends, refined_localizations, refined_masks, refined_segmentations
    success, outlines = ibs.ibeis_plugin_curvrank_outline(*args, **config)

    values = ibs.ibeis_plugin_curvrank_trailing_edges(success, outlines, **config)
    success, trailing_edges = values

    values = ibs.ibeis_plugin_curvrank_curvatures(success, trailing_edges, **config)
    success, curvatures = values

    values = ibs.ibeis_plugin_curvrank_curvature_descriptors(success, curvatures, **config)
    success, curvature_descriptors = values

    return success, curvature_descriptors


@register_ibs_method
def ibeis_plugin_curvrank_pipeline_aggregate(ibs, aid_list, success_list,
                                             descriptor_dict_list):
    r"""
    Args:
        ibs       (IBEISController): IBEIS controller object
        success_list: output of ibeis_plugin_curvrank_outline
        outlines (list of np.ndarray): output of ibeis_plugin_curvrank_outline

    Returns:
        success_list_
        curvature_descriptors

    CommandLine:
        python -m ibeis_curvrank._plugin --test-ibeis_plugin_curvrank_pipeline_aggregate

    Example:
        >>> # ENABLE_DOCTEST
        >>> from ibeis_curvrank._plugin import *  # NOQA
        >>> import ibeis
        >>> from ibeis.init import sysres
        >>> dbdir = sysres.ensure_testdb_curvrank()
        >>> ibs = ibeis.opendb(dbdir=dbdir)
        >>> aid_list = ibs.get_image_aids(1)
        >>> values = ibs.ibeis_plugin_curvrank_pipeline_compute(aid_list)
        >>> success_list, curvature_descriptor_dicts = values
        >>> lnbnn_dict = ibs.ibeis_plugin_curvrank_pipeline_aggregate(aid_list, success_list, curvature_descriptor_dicts)
        >>> hash_list = [
        >>>     ut.hash_data(lnbnn_dict[scale])
        >>>     for scale in sorted(list(lnbnn_dict.keys()))
        >>> ]
        >>> assert ut.hash_data(hash_list) in ['eegzjulonluhvyhnsfckhihpdxtlnxsz']
    """
    lnbnn_dict = {}
    zipped = zip(aid_list, success_list, descriptor_dict_list)
    for aid, success, descriptor_dict in zipped:
        if not success:
            continue

        for scale in descriptor_dict:
            if scale not in lnbnn_dict:
                lnbnn_dict[scale] = {
                    'descriptors': [],
                    'aids'       : [],
                }

            descriptors = descriptor_dict[scale]
            aids = [aid] * descriptors.shape[0]

            lnbnn_dict[scale]['descriptors'].append(descriptors)
            lnbnn_dict[scale]['aids'].append(aids)

    for scale in lnbnn_dict:
        descriptors = np.vstack(lnbnn_dict[scale]['descriptors'])
        assert np.allclose(
            np.linalg.norm(descriptors, axis=1),
            np.ones(descriptors.shape[0])
        )

        aids = np.hstack(lnbnn_dict[scale]['aids'])
        lnbnn_dict[scale] = (descriptors, aids, )

    return lnbnn_dict


@register_ibs_method
def ibeis_plugin_curvrank_pipeline(ibs, imageset_rowid=None, aid_list=None,
                                   config={}, use_depc=USE_DEPC, verbose=False):
    r"""
    Args:
        ibs       (IBEISController): IBEIS controller object
        success_list: output of ibeis_plugin_curvrank_outline
        outlines (list of np.ndarray): output of ibeis_plugin_curvrank_outline

    Returns:
        success_list_
        curvature_descriptors

    CommandLine:
        python -m ibeis_curvrank._plugin --test-ibeis_plugin_curvrank_pipeline
        python -m ibeis_curvrank._plugin --test-ibeis_plugin_curvrank_pipeline:0
        python -m ibeis_curvrank._plugin --test-ibeis_plugin_curvrank_pipeline:1

    Example:
        >>> # ENABLE_DOCTEST
        >>> from ibeis_curvrank._plugin import *  # NOQA
        >>> import ibeis
        >>> from ibeis.init import sysres
        >>> dbdir = sysres.ensure_testdb_curvrank()
        >>> ibs = ibeis.opendb(dbdir=dbdir)
        >>> aid_list = ibs.get_image_aids(1)
        >>> lnbnn_dict, aid_list = ibs.ibeis_plugin_curvrank_pipeline(aid_list=aid_list, use_depc=False)
        >>> hash_list = [
        >>>     ut.hash_data(lnbnn_dict[scale])
        >>>     for scale in sorted(list(lnbnn_dict.keys()))
        >>> ]
        >>> assert ut.hash_data(hash_list) in ['eegzjulonluhvyhnsfckhihpdxtlnxsz']

    Example1:
        >>> # ENABLE_DOCTEST
        >>> from ibeis_curvrank._plugin import *  # NOQA
        >>> import ibeis
        >>> from ibeis.init import sysres
        >>> dbdir = sysres.ensure_testdb_curvrank()
        >>> ibs = ibeis.opendb(dbdir=dbdir)
        >>> aid_list = ibs.get_image_aids(1)
        >>> lnbnn_dict, aid_list = ibs.ibeis_plugin_curvrank_pipeline(aid_list=aid_list, use_depc=True)
        >>> hash_list = [
        >>>     ut.hash_data(lnbnn_dict[scale])
        >>>     for scale in sorted(list(lnbnn_dict.keys()))
        >>> ]
        >>> assert ut.hash_data(hash_list) in ['eegzjulonluhvyhnsfckhihpdxtlnxsz']
    """
    if aid_list is None:
        aid_list = ibs.get_imageset_aids(imageset_rowid)

    # Compute Curvature Descriptors
    if verbose:
        print('\tCompute Curvature Pipeline')

    if use_depc:
        success_list         = ibs.depc_annot.get('curvature_descriptor', aid_list, 'success',    config=config)
        descriptor_dict_list = ibs.depc_annot.get('curvature_descriptor', aid_list, 'descriptor', config=config)
    else:
        values = ibs.ibeis_plugin_curvrank_pipeline_compute(aid_list, config=config)
        success_list, descriptor_dict_list = values

    if verbose:
        print('\tAggregate Pipeline Results')

    lnbnn_dict = ibs.ibeis_plugin_curvrank_pipeline_aggregate(
        aid_list,
        success_list,
        descriptor_dict_list
    )

    return lnbnn_dict, aid_list


if __name__ == '__main__':
    r"""
    CommandLine:
        python -m ibeis_curvrank._plugin --allexamples
    """
    import multiprocessing
    multiprocessing.freeze_support()  # for win32
    import utool as ut  # NOQA
    ut.doctest_funcs()
