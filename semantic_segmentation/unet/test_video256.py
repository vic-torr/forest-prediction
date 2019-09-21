import argparse
import torch
import os
import numpy as np
from tqdm import tqdm
import data_loader.data_loaders as module_data
import model.loss as module_loss
import model.metric as module_metric
import model.model as module_arch
import time
from parse_config import ConfigParser
from utils.util import save_images, NormalizeInverse, save_video_images
from torch.nn import functional as F

def _threshold_outputs(outputs, output_threshold=0.3):
    idx = outputs > output_threshold
    outputs = np.zeros(outputs.shape, dtype=np.int8)
    outputs[idx] = 1
    return outputs

def _fast_hist(outputs, targets, num_classes=2):
    # print(outputs.shape, targets.shape)
    mask = (targets >= 0) & (targets < num_classes)
    hist = np.bincount(
        num_classes * targets[mask].astype(int) +
        outputs[mask], minlength=num_classes ** 2).reshape(num_classes, num_classes)
    return hist

def evaluate(outputs=None, targets=None, hist=None, num_classes=2):
    if hist is None:
        hist = np.zeros((num_classes, num_classes))
        for lp, lt in zip(outputs, targets):
            hist += _fast_hist(lp.flatten(), lt.flatten(), num_classes)
    # axis 0: gt, axis 1: prediction
    eps = 1e-10
    acc = np.diag(hist).sum() / hist.sum()
    acc_cls = np.diag(hist) / hist.sum(axis=1)
    acc_cls = np.nanmean(acc_cls)
    iu = np.diag(hist) / (hist.sum(axis=1) + hist.sum(axis=0) - np.diag(hist))
    mean_iu = np.nanmean(iu)
    freq = hist.sum(axis=1) / hist.sum()
    fwavacc = (freq[freq > 0] * iu[freq > 0]).sum()

    true_pos = hist[1, 1]
    false_pos = hist[0, 1]
    false_neg = hist[1, 0]
    precision = true_pos / (true_pos + false_pos + eps)
    recall = true_pos / (true_pos + false_neg + eps)
    f1_score = 2. * ((precision * recall) / (precision + recall + eps))

    return acc, acc_cls, mean_iu, fwavacc, precision, recall, f1_score

def update_individual_hists(data, target, hist, device, model):
    data, target = data.to(device, dtype=torch.float), target.to(device, dtype=torch.float)
    output = model(data)
    output_probs = F.sigmoid(output)
    binary_target = _threshold_outputs(target.data.cpu().numpy().flatten())
    output_binary = _threshold_outputs(
        output_probs.data.cpu().numpy().flatten())
    hist += _fast_hist(output_binary, binary_target)
    return output_binary.reshape(-1, 1, 256, 256)

def main(config):
    logger = config.get_logger('test')
    # setup data_loader instances
    batch_size = 1
    if config['data_loader_val']['args']['max_dataset_size'] == 'inf':
        max_dataset_size = float('inf')
    else:
        max_dataset_size = config['data_loader_val']['args']['max_dataset_size']
    data_loader = getattr(module_data, config['data_loader_val']['type'])(
        img_dir=config['data_loader_val']['args']['img_dir'],
        label_dir=config['data_loader_val']['args']['img_dir'],
        video_dir=config['data_loader_val']['args']['img_dir'],
        batch_size=batch_size,
        max_dataset_size=max_dataset_size,
        shuffle=False,
        num_workers=1
    )
    landsat_mean, landsat_std = (0.3326, 0.3570, 0.2224), (0.1059, 0.1086, 0.1283)
    # build model architecture
    model = config.initialize('arch', module_arch)
    logger.info(model)

    # get function handles of loss and metrics
    loss_fn = config.initialize('loss', module_loss)
    # loss_fn = getattr(module_loss, config['loss'])
    metric_fns = [getattr(module_metric, met) for met in config['metrics']]

    logger.info('Loading checkpoint: {} ...'.format(config.resume))
    checkpoint = torch.load(config.resume)
    state_dict = checkpoint['state_dict']
    if config['n_gpu'] > 1:
        model = torch.nn.DataParallel(model)
    model.load_state_dict(state_dict)

    # prepare model for testing
    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    model = model.to(device)
    model.eval()

    total_loss = 0.0
    total_metrics = torch.zeros(len(metric_fns))
    pred_dir = '/'.join(str(config.resume.absolute()).split('/')[:-1])
    # pred_dir = os.path.join(pred_dir, 'predictions')
    out_dir = os.path.join(pred_dir, 'video')
    if not os.path.isdir(pred_dir):
        os.makedirs(pred_dir)
    if not os.path.isdir(out_dir):
        os.makedirs(out_dir)
    # out_dir = '/'.join(str(config.resume.absolute()).split('/')[:-1])
    # out_dir = os.path.join(out_dir, 'predictions')
    hist = np.zeros((2,2))
    hist2013 = np.zeros((2,2))
    hist2014 = np.zeros((2,2))
    hist2015 = np.zeros((2,2))
    hist2016 = np.zeros((2,2))
    hist2017 = np.zeros((2,2))

    # This script only supports batch=1
    with torch.no_grad():
        for i, batch in enumerate(tqdm(data_loader)):
        # for i, (data, target) in enumerate(tqdm(data_loader)):
            init_time = time.time()
            loss = None
            img_arr2013, mask_arr2013 = batch['2013']['img_arr'], batch['2013']['mask_arr']
            img_arr2014, mask_arr2014 = batch['2014']['img_arr'], batch['2014']['mask_arr']
            img_arr2015, mask_arr2015 = batch['2015']['img_arr'], batch['2015']['mask_arr']
            img_arr2016, mask_arr2016 = batch['2016']['img_arr'], batch['2016']['mask_arr']
            img_arr2017, mask_arr2017 = batch['2017']['img_arr'], batch['2017']['mask_arr']

            uimg_arr2013, uimg_arr2014, uimg_arr2015, uimg_arr_2016, uimg_arr_2017 = \
                normalize_inverse(img_arr2013, landsat_mean, landsat_std), \
                normalize_inverse(img_arr2014, landsat_mean, landsat_std), \
                normalize_inverse(img_arr2015, landsat_mean, landsat_std), \
                normalize_inverse(img_arr2016, landsat_mean, landsat_std), \
                normalize_inverse(img_arr2017, landsat_mean, landsat_std)

            pred2013 = update_individual_hists(img_arr2013, mask_arr2013, hist2013, device, model)
            pred2014 = update_individual_hists(img_arr2014, mask_arr2014, hist2014, device, model)
            pred2015 = update_individual_hists(img_arr2015, mask_arr2015, hist2015, device, model)
            pred2016 = update_individual_hists(img_arr2016, mask_arr2016, hist2016, device, model)
            pred2017 = update_individual_hists(img_arr2017, mask_arr2017, hist2017, device, model)

            images = {
                '2013':{
                    'img': uim_arr2013.cpu().numpy(),
                    'gt': mask_arr2013.cpu().numpy(),
                    'pred': pred2013.cpu().numpy()
                },
                '2014':{
                    'img': uim_arr2014.cpu().numpy(),
                    'gt': mask_arr2014.cpu().numpy(),
                    'pred': pred2014.cpu().numpy()
                },
                '2015':{
                    'img': uim_arr2015.cpu().numpy(),
                    'gt': mask_arr2015.cpu().numpy(),
                    'pred': pred2015.cpu().numpy()
                },
                '2016':{
                    'img': uim_arr2016.cpu().numpy(),
                    'gt': mask_arr2016.cpu().numpy(),
                    'pred': pred2016.cpu().numpy()
                },
                '2017':{
                    'img': uim_arr2017.cpu().numpy(),
                    'gt': mask_arr2017.cpu().numpy(),
                    'pred': pred2017.cpu().numpy()
                }
            }
            save_video_images256(images, out_dir, i*batch_size)
            # computing loss, metrics on test set
            loss = loss_fn(output, target_cover)
            batch_size = datavd.shape[0]
            total_loss += loss.item() * batch_size
            # for i, metric in enumerate(metric_fns):
            #     total_metrics[i] += metric(output, target.float()) * batch_size
    acc, acc_cls, mean_iu, fwavacc, precision, recall, f1_score = \
        evaluate(hist=hist)

    accq1, acc_clsq1, mean_iuq1, fwavaccq1, precisionq1, recallq1, f1_scoreq1 = \
        evaluate(hist=histq1)

    accq2, acc_clsq2, mean_iuq2, fwavaccq2, precisionq2, recallq2, f1_scoreq2 = \
        evaluate(hist=histq2)

    n_samples = len(data_loader.sampler)
    log = {'loss': total_loss / n_samples,
        'acc': acc, 'mean_iu': mean_iu, 'fwavacc': fwavacc,
        'precision': precision, 'recall': recall, 'f1_score': f1_score
    }

    logq1 = {'lossq1': total_loss / n_samples,
        'acc': accq1, 'mean_iu': mean_iuq1, 'fwavacc': fwavaccq1,
        'precision': precisionq1, 'recall': recallq1, 'f1_score': f1_scoreq1
    }

    logq2 = {'lossq2': total_loss / n_samples,
        'acc': accq2, 'mean_iu': mean_iuq2, 'fwavacc': fwavaccq2,
        'precision': precisionq2, 'recall': recallq2, 'f1_score': f1_scoreq2
    }
    # log.update({
    #     met.__name__: total_metrics[i].item() / n_samples for i, met in enumerate(metric_fns)
    # })
    logger.info(log)
    logger.info(logq1)
    logger.info(logq2)

def normalize_inverse(batch, mean, std, input_type='one'):

    with torch.no_grad():
        img = batch.clone()
        ubatch = torch.Tensor(batch.shape)

        ubatch[:, 0, :, :] = img[:, 0, :, :] * std[0] + mean[0]
        ubatch[:, 1, :, :] = img[:, 1, :, :] * std[1] + mean[1]
        ubatch[:, 2, :, :] = img[:, 2, :, :] * std[2] + mean[2]
    return ubatch

if __name__ == '__main__':
    args = argparse.ArgumentParser(description='PyTorch Template')

    args.add_argument('-r', '--resume', default=None, type=str,
                      help='path to latest checkpoint (default: None)')
    args.add_argument('-d', '--device', default=None, type=str,
                      help='indices of GPUs to enable (default: all)')
    config = ConfigParser(args)
    main(config)