import numpy as np
import os
import tgt
from scipy.io.wavfile import read
import pyworld as pw
import torch
import audio as Audio
from utils import get_alignment
import hparams as hp
from jamo import h2j
import codecs

def prepare_align(in_dir, meta):
    with open(os.path.join(in_dir, meta), encoding='utf-8') as f:
        for line in f:
            parts = line.strip().split('|')
            basename, text = parts[0], parts[3]

            basename=basename.replace('.wav','.txt')
            
            with open(os.path.join(in_dir,'wavs',basename),'w') as f1:
                f1.write(text)

def build_from_path(in_dir, out_dir, meta):
    train, val = list(), list()
    f0_max, f0_min = energy_max, energy_min = 0, 1000000
    n_frames = 0
    
    with open(os.path.join(in_dir, meta), encoding='utf-8') as f:
        for index, line in enumerate(f):

            parts = line.strip().split('|')
            basename, text = parts[0], parts[3]

            ret = process_utterance(in_dir, out_dir, basename)

            if ret is None:
                continue
            else:
                info, f_max, f_min, e_max, e_min, n = ret
            
            if basename[0] == '1':
                val.append(info)
            else:
                train.append(info)

            if index % 100 == 0:
                print("Done %d" % index)

            f0_max, f0_min = max(f0_max, f_max), min(f0_min, f_min)
            energy_max, energy_min = max(energy_max, e_max), min(energy_min, e_min)
            n_frames += n

    with open(os.path.join(out_dir, 'stat.txt'), 'w', encoding='utf-8') as f:
        strs = ['Total time: {} hours'.format(n_frames*hp.hop_length/hp.sampling_rate/3600),
                'Total frames: {}'.format(n_frames),
                'Min F0: {}'.format(f0_min),
                'Max F0: {}'.format(f0_max),
                'Min energy: {}'.format(energy_min),
                'Max energy: {}'.format(energy_max)]

        for s in strs:
            print(s)
            f.write(s+'\n')

    return [r for r in train if r is not None], [r for r in val if r is not None]


def process_utterance(in_dir, out_dir, basename):
    wav_bak_basename=basename.replace('.wav','')
    basename = wav_bak_basename[2:]
    wav_bak_path = os.path.join(in_dir, "wavs_bak", "{}.wav".format(wav_bak_basename))
    wav_path = os.path.join(in_dir, 'wavs', '{}.wav'.format(basename))

    # Convert kss data into PCM encoded wavs
    if not os.path.isfile(wav_path):
        os.system("ffmpeg -i {} -ac 1 -ar 22050 {}".format(wav_bak_path, wav_path))    
    tg_path = os.path.join(out_dir, 'TextGrid', '{}.TextGrid'.format(basename)) 
    
    # Get alignments
    textgrid = tgt.io.read_textgrid(tg_path)
    phone, duration, start, end = get_alignment(textgrid.get_tier_by_name('phones'))
    text = '{'+ '}{'.join(phone) + '}' # '{A}{B}{$}{C}', $ represents silent phones
    text = text.replace('{$}', ' ')    # '{A}{B} {C}'
    text = text.replace('}{', ' ')     # '{A B} {C}'

    if start >= end:
        return None

    # Read and trim wav files
    _, wav = read(wav_path)
    wav = wav[int(hp.sampling_rate*start):int(hp.sampling_rate*end)].astype(np.float32)

    # Compute fundamental frequency
    f0, _ = pw.dio(wav.astype(np.float64), hp.sampling_rate, frame_period=hp.hop_length/hp.sampling_rate*1000)
    f0 = f0[:sum(duration)]

    # Compute mel-scale spectrogram and energy
    mel_spectrogram, energy = Audio.tools.get_mel_from_wav(torch.FloatTensor(wav))
    mel_spectrogram = mel_spectrogram.numpy().astype(np.float32)[:, :sum(duration)]
    energy = energy.numpy().astype(np.float32)[:sum(duration)]

    if mel_spectrogram.shape[1] >= hp.max_seq_len:
        return None

    # Save alignment
    ali_filename = '{}-ali-{}.npy'.format(hp.dataset, basename)
    np.save(os.path.join(out_dir, 'alignment', ali_filename), duration, allow_pickle=False)

    # Save fundamental prequency
    f0_filename = '{}-f0-{}.npy'.format(hp.dataset, basename)
    np.save(os.path.join(out_dir, 'f0', f0_filename), f0, allow_pickle=False)

    # Save energy
    energy_filename = '{}-energy-{}.npy'.format(hp.dataset, basename)
    np.save(os.path.join(out_dir, 'energy', energy_filename), energy, allow_pickle=False)

    # Save spectrogram
    mel_filename = '{}-mel-{}.npy'.format(hp.dataset, basename)
    np.save(os.path.join(out_dir, 'mel', mel_filename), mel_spectrogram.T, allow_pickle=False)
    
    return '|'.join([basename, text]), max(f0), min([f for f in f0 if f != 0]), max(energy), min(energy), mel_spectrogram.shape[1]
