from __future__ import absolute_import, division, print_function
from ibeis.control import controller_inject  # NOQA
import numpy as np
import utool as ut
import vtool as vt
import dtool


_, register_ibs_method = controller_inject.make_ibs_register_decorator(__name__)
register_api = controller_inject.get_ibeis_flask_api(__name__)
register_preproc_image = controller_inject.register_preprocs['image']
register_preproc_annot = controller_inject.register_preprocs['annot']


URL_DICT = {
    'localization': 'https://lev.cs.rpi.edu/public/models/curvrank.localization.weights.pkl',
    'segmentation': 'https://lev.cs.rpi.edu/public/models/curvrank.segmentation.weights.pkl',
}


@register_ibs_method
def ibeis_plugin_curvrank_example(ibs):
    from ibeis_curvrank.example_workflow import example
    example()


@register_ibs_method
def ibeis_plugin_curvrank_aids(ibs, aid_list):

    results_list = []

    return results_list


@register_ibs_method
def ibeis_plugin_curvrank(ibs, image_filepath_list, name_list, flip_list):
    results_list = []
    return results_list


class PreprocessConfig(dtool.Config):
    def get_param_info_list(self):
        return [
            ut.ParamInfo('preprocess_height', 256),
            ut.ParamInfo('preprocess_width', 256),
            ut.ParamInfo('ext', '.png', hideif='.png'),
        ]


@register_preproc_image(
    tablename='preprocess', parents=['images'],
    colnames=['resized_img', 'resized_width', 'resized_height', 'mask_img', 'mask_width', 'mask_height', 'pretransform'],
    coltypes=[('extern', vt.imread, vt.imwrite), int, int, ('extern', ut.partial(vt.imread, grayscale=True), vt.imwrite), int, int, np.ndarray],
    configclass=PreprocessConfig,
    fname='curvrank',
    rm_extern_on_delete=True,
    chunksize=256,
)
def ibeis_plugin_curvrank_preprocessing_depc(depc, gid_list, config=None):
    r"""
    Pre-process images for CurvRank with Dependency Cache (depc)

    Args:
        depc      (Dependency Cache): IBEIS dependency cache object
        gid_list  (list of int): list of image rowids (gids)
        config    (PreprocessConfig): config for depcache

    CommandLine:
        python -m ibeis_curvrank._plugin --test-ibeis_plugin_curvrank_preprocessing_depc

    Example1:
        >>> # ENABLE_DOCTEST
        >>> from ibeis_curvrank._plugin import *  # NOQA
        >>> import ibeis
        >>> from ibeis.init import sysres
        >>> dbdir = sysres.ensure_testdb_curvrank()
        >>> ibs = ibeis.opendb(dbdir=dbdir)
        >>> gid_list = ibs.get_valid_gids()[0:1]
        >>> config = {
        >>>     'preprocess_height': 256,
        >>>     'preprocess_width': 256,
        >>> }
        >>> resized_images = ibs.depc_image.get('preprocess', gid_list, 'resized_img',  config=config)
        >>> resized_masks  = ibs.depc_image.get('preprocess', gid_list, 'mask_img',     config=config)
        >>> pre_transforms = ibs.depc_image.get('preprocess', gid_list, 'pretransform', config=config)
        >>> resized_image = resized_images[0]
        >>> resized_mask  = resized_masks[0]
        >>> pre_transform = pre_transforms[0]
        >>> assert ut.hash_data(resized_image) == 'ynbsgqgfutslspmatpenvcbtgedsyzoo'
        >>> assert ut.hash_data(resized_mask)  == 'mnhartnytowmmhskblocubqmzhbofynr'
        >>> result = pre_transform
        >>> print(result)
        [[ 0.11077456  0.          0.        ]
         [ 0.          0.11077456 38.        ]
         [ 0.          0.          1.        ]]
    """
    height = config['preprocess_height']
    width = config['preprocess_width']

    ibs = depc.controller
    values = ibs.ibeis_plugin_curvrank_preprocessing(gid_list, height=height, width=width)
    resized_images, resized_masks, pre_transforms = values

    zipped = zip(resized_images, resized_masks, pre_transforms)
    for resized_image, resized_mask, pre_transform in zipped:
        resized_width, resized_height = vt.get_size(resized_image)
        mask_width, mask_height = vt.get_size(resized_mask)

        yield (
            resized_image,
            resized_width,
            resized_height,
            resized_mask,
            mask_width,
            mask_height,
            pre_transform,
        )


@register_ibs_method
def ibeis_plugin_curvrank_preprocessing(ibs, gid_list, height=256, width=256):
    r"""
    Pre-process images for CurvRank

    Args:
        ibs       (IBEISController): IBEIS controller object
        gid_list  (list of int): list of image rowids (gids)

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
        >>> gid_list = ibs.get_valid_gids()[0:1]
        >>> values = ibs.ibeis_plugin_curvrank_preprocessing(gid_list, width=256, height=256)
        >>> resized_images, resized_masks, pre_transforms = values
        >>> resized_image = resized_images[0]
        >>> resized_mask  = resized_masks[0]
        >>> pre_transform = pre_transforms[0]
        >>> assert ut.hash_data(resized_image) == 'ynbsgqgfutslspmatpenvcbtgedsyzoo'
        >>> assert ut.hash_data(resized_mask) == 'mnhartnytowmmhskblocubqmzhbofynr'
        >>> result = pre_transform
        >>> print(result)
        [[ 0.11077456  0.          0.        ]
         [ 0.          0.11077456 38.        ]
         [ 0.          0.          1.        ]]
    """
    import ibeis_curvrank.functional as F

    image_list = ibs.get_images(gid_list)

    metadata_list = ibs.get_image_metadata(gid_list)
    viewpoint_list = [metadata.get('viewpoint', None) for metadata in metadata_list]
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
                                       model_tag='localization', height=256,
                                       width=256):
    r"""
    Localize images for CurvRank

    Args:
        ibs       (IBEISController): IBEIS controller object
        model_tag  (string): Key to URL_DICT entry for this model
        resized_images (list of np.ndarray): widthXheightX3 color channels
        resized_masks (list of np.ndarray): heightXwidth greyscale images
        height: height of resized images
        width: width of resized images

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
        >>> dbdir = sysres.ensure_testdb_curvrank()
        >>> ibs = ibeis.opendb(dbdir=dbdir)
        >>> gid_list = ibs.get_valid_gids()[0:1]
        >>> values = ibs.ibeis_plugin_curvrank_preprocessing(gid_list, width=256, height=256)
        >>> resized_images, resized_masks, pre_transforms = values
        >>> values = ibs.ibeis_plugin_curvrank_localization(resized_images,resized_masks, width=256, height=256)
        >>> localized_images, localized_masks, loc_transforms = values
        >>> localized_image = localized_images[0]
        >>> localized_mask  = localized_masks[0]
        >>> loc_transform = loc_transforms[0]
        >>> # localized_image appears to differ very slightly in ubuntu vs. mac. Hashes below for each respectively.
        >>> #TODO verify that mac/ubuntu values are consistent on those OSes
        >>> assert ut.hash_data(localized_image) in ['mbwtvdojxaidtmcrqvyamkgpchzupfsh','pbgpmewfannhnrsrfxixdnhwczbkordr']
        >>> assert ut.hash_data(localized_mask)  == 'jhoiquabhpowhrsjkgpvsymnwbpqnvaw'
        >>> # for above reasons, some voodoo to compare loc_transform
        >>> loc_transform_ubuntu = np.array([[ 0.63338047,  0.12626281, -0.11245003],
        >>>                                  [-0.12531438,  0.63420326, -0.00189855],
        >>>                                  [ 0.        ,  0.        ,  1.        ]])
        >>> assert np.all(np.abs(loc_transform - loc_transform_ubuntu) < 1e-6)
    """
    import ibeis_curvrank.functional as F
    from ibeis_curvrank import localization, model, theano_funcs

    model_url = URL_DICT.get(model_tag, None)
    assert model_url is not None
    weight_filepath = ut.grab_file_url(model_url, appname='ibeis_curvrank', check_hash=True)
    layers = localization.build_model((None, 3, height, width))
    model.load_weights([
        layers['trans'], layers['loc']],
        weight_filepath
    )
    localization_func = theano_funcs.create_localization_infer_func(layers)

    values = F.localize(resized_images, resized_masks, height, width,
                        localization_func)
    localized_images, localized_masks, loc_transforms = values

    # Convert these to uint8 for compatibility with depc
    localized_masks = [
        np.around(localized_mask).astype(np.uint8)
        for localized_mask in localized_masks
    ]

    return localized_images, localized_masks, loc_transforms


class LocalizationConfig(dtool.Config):
    def get_param_info_list(self):
        return [
            ut.ParamInfo('localization_model_tag', 'localization'),
            ut.ParamInfo('localization_height', 256),
            ut.ParamInfo('localization_width', 256),
            ut.ParamInfo('ext', '.png', hideif='.png'),
        ]


@register_preproc_image(
    tablename='localization', parents=['preprocess'],
    colnames=['localized_img', 'localized_width', 'localized_height', 'mask_img', 'mask_width', 'mask_height', 'transform'],
    coltypes=[('extern', vt.imread, vt.imwrite), int, int, ('extern', ut.partial(vt.imread, grayscale=True), vt.imwrite), int, int, np.ndarray],
    configclass=LocalizationConfig,
    fname='curvrank',
    rm_extern_on_delete=True,
    chunksize=256,
)
# chunksize defines the max number of 'yield' below that will be called in a chunk
# so you would decrease chunksize on expensive calculations
def ibeis_plugin_curvrank_localization_depc(depc, preprocess_rowid_list, config=None):
    r"""
    Localize images for CurvRank with Dependency Cache (depc)

    CommandLine:
        python -m ibeis_curvrank._plugin --test-ibeis_plugin_curvrank_localization_depc

    Example1:
        >>> # ENABLE_DOCTEST
        >>> from ibeis_curvrank._plugin import *  # NOQA
        >>> import ibeis
        >>> from ibeis.init import sysres
        >>> dbdir = sysres.ensure_testdb_curvrank()
        >>> ibs = ibeis.opendb(dbdir=dbdir)
        >>> gid_list = ibs.get_valid_gids()[0:1]
        >>> config = {
        >>>     'preprocess_height': 256,
        >>>     'preprocess_width': 256,
        >>>     'localization_height': 256,
        >>>     'localization_width': 256,
        >>>     'localization_model_tag': 'localization'
        >>> }
        >>> localized_images = ibs.depc_image.get('localization', gid_list, 'localized_img',  config=config)
        >>> localized_masks  = ibs.depc_image.get('localization', gid_list, 'mask_img',     config=config)
        >>> loc_transforms = ibs.depc_image.get('localization', gid_list, 'transform', config=config)
        >>> localized_image = localized_images[0]
        >>> localized_mask  = localized_masks[0]
        >>> loc_transform = loc_transforms[0]
        >>> # localized_image appears to differ very slightly in ubuntu vs. mac. Hashes below for each respectively.
        >>> #TODO verify that mac/ubuntu values are consistent on those OSes
        >>> assert ut.hash_data(localized_image) in ['mbwtvdojxaidtmcrqvyamkgpchzupfsh','pbgpmewfannhnrsrfxixdnhwczbkordr']
        >>> assert ut.hash_data(localized_mask)  == 'jhoiquabhpowhrsjkgpvsymnwbpqnvaw'
        >>> # for above reasons, some voodoo to compare loc_transform
        >>> loc_transform_ubuntu = np.array([[ 0.63338047,  0.12626281, -0.11245003],
        >>>                                  [-0.12531438,  0.63420326, -0.00189855],
        >>>                                  [ 0.        ,  0.        ,  1.        ]])
        >>> assert np.all(np.abs(loc_transform - loc_transform_ubuntu) < 1e-6)
    """

    height = config['localization_height']
    width  = config['localization_width']
    model_tag = config['localization_model_tag']
    ibs = depc.controller
    # fetch resized image
    resized_images = depc.get_native('preprocess', preprocess_rowid_list, 'resized_img')
    # fetch resized mask
    resized_masks = depc.get_native('preprocess', preprocess_rowid_list, 'mask_img')
    # call function above
    values = ibs.ibeis_plugin_curvrank_localization(resized_images, resized_masks,
                                                    model_tag=model_tag, height=height,
                                                    width=width)
    localized_images, localized_masks, loc_transforms = values

    # yield each column defined in register_preproc_image
    zipped = zip(localized_images, localized_masks, loc_transforms)
    for localized_image, localized_mask, loc_transform in zipped:
        localized_width, localized_height = vt.get_size(localized_image)
        mask_width, mask_height = vt.get_size(localized_mask)
        yield (
            localized_image,
            localized_width,
            localized_height,
            localized_mask,
            mask_width,
            mask_height,
            loc_transform,
        )


if __name__ == '__main__':
    r"""
    CommandLine:
        python -m ibeis_curvrank._plugin
        python -m ibeis_curvrank._plugin --allexamples
    """
    import multiprocessing
    multiprocessing.freeze_support()  # for win32
    import utool as ut  # NOQA
    ut.doctest_funcs()