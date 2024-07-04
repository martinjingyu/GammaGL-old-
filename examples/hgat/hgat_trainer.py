# !/usr/bin/env python3
# -*- coding:utf-8 -*-

# @Time    : 2022/04/16 25:16
# @Author  : Jingyu Huang 
# @FileName: hgat_trainer.py
import os
os.environ['CUDA_VISIBLE_DEVICES'] = '2'
os.environ['TL_BACKEND'] = 'tensorflow'
# 0:Output all; 1:Filter out INFO; 2:Filter out INFO and WARNING; 3:Filter out INFO, WARNING, and ERROR
import numpy as np
import argparse
import tensorlayerx as tlx
import gammagl.transforms as T
from gammagl.datasets import AGNews,IMDB, OHSUMED, Twitter


from gammagl.models import HGATModel;
from gammagl.utils import mask_to_index, set_device
from tensorlayerx.model import TrainOneStep, WithLoss

class SemiSpvzLoss(WithLoss):
    def __init__(self, net, loss_fn):
        super(SemiSpvzLoss, self).__init__(backbone=net, loss_fn=loss_fn)

    def forward(self, data, y, node_tpye):
        logits = self.backbone_network(data['x_dict'], data['edge_index_dict'], data['num_nodes_dict'])
        train_logits = tlx.gather(logits[node_tpye], data['train_idx'])
        train_y = tlx.gather(data['y'], data['train_idx'])
        loss = self._loss_fn(train_logits, train_y)
        return loss


def calculate_acc(logits, y, metrics):
    """
    Args:
        logits: node logits
        y: node labels
        metrics: tensorlayerx.metrics

    Returns:
        rst
    """

    metrics.update(logits, y)
    rst = metrics.result()
    metrics.reset()
    return rst


def main(args):
    # NOTE: ONLY IMDB DATASET
    # If you want to execute HAN on other dataset (e.g. ACM),
    # you will be needed to init `metepaths`
    # and set `movie` string with proper values.
    # path = osp.join(osp.dirname(osp.realpath(__file__)), '../IMDB')
    if(args.dataset=="IMDB"):
        dataset = IMDB(args.dataset_path)
        graph = dataset[0]
        print(graph)
        y = graph['movie'].y
        node_type = 'movie'


        
    if(args.dataset=="agnews"):
        dataset = AGNews(args.dataset_path)
        graph = dataset[0]
        print(graph)
        y = graph['text'].y
        node_type = 'text'


    if(args.dataset=="ohsumed"):
        dataset = OHSUMED(args.dataset_path)
        graph = dataset[0]
        print(graph)
        y = graph['documents'].y
        node_type = 'documents'



    if(args.dataset=="twitter"):
        dataset = Twitter(args.dataset_path)
        graph = dataset[0]
        print(graph)
        y = graph['twitter'].y
        node_type = 'twitter'



    # for mindspore, it should be passed into node indices
    train_idx = mask_to_index(graph[node_type].train_mask)
    test_idx = mask_to_index(graph[node_type].test_mask)
    val_idx = mask_to_index(graph[node_type].val_mask)
    node_type_list = graph.metadata()[0]
    in_channel = {}
    num_nodes_dict = {}
    for node_type in node_type_list:
        in_channel[node_type]=graph.x_dict[node_type].shape[1]
        num_nodes_dict[node_type]=graph.x_dict[node_type].shape[0]


    net = HGATModel(
        in_channels=in_channel,
        out_channels=len(np.unique(graph.y.cpu())), # graph.num_classes,
        metadata=graph.metadata(),
        drop_rate=0.5,
        hidden_channels=args.hidden_dim,
        name = 'hgat',
    )
        

    optimizer = tlx.optimizers.Adam(lr=args.lr, weight_decay=args.l2_coef)
    metrics = tlx.metrics.Accuracy()
    train_weights = net.trainable_weights

    loss_func = tlx.losses.softmax_cross_entropy_with_logits
    semi_spvz_loss = SemiSpvzLoss(net, loss_func)
    train_one_step = TrainOneStep(semi_spvz_loss, optimizer, train_weights)

    data = {
        "x_dict": graph.x_dict,
        "y": y,
        "edge_index_dict": graph.edge_index_dict,
        "train_idx": train_idx,
        "test_idx": test_idx,
        "val_idx": val_idx,
        "num_nodes_dict": num_nodes_dict,
    }
    print(np.unique(y.cpu()))
    best_val_acc = 0

    for epoch in range(args.n_epoch):
        net.set_train()
        train_loss = train_one_step(data, y, node_type)
        net.set_eval()

        logits = net(data['x_dict'], data['edge_index_dict'], data['num_nodes_dict'])
        val_logits = tlx.gather(logits[node_type], data['val_idx'])
        val_y = tlx.gather(data['y'], data['val_idx'])
        val_acc = calculate_acc(val_logits, val_y, metrics)

        print("Epoch [{:0>3d}]  ".format(epoch + 1)
              + "   train_loss: {:.4f}".format(train_loss.item())
              # + "   train_acc: {:.4f}".format(train_acc)
              + "   val_acc: {:.4f}".format(val_acc))

        # save best model on evaluation set
        if val_acc > best_val_acc:
            best_val_acc = val_acc
            net.save_weights(args.best_model_path + net.name + ".npz", format='npz_dict')

    net.load_weights(args.best_model_path + net.name + ".npz", format='npz_dict')
    net.set_eval()
    logits = net(data['x_dict'], data['edge_index_dict'], data['num_nodes_dict'])
    test_logits = tlx.gather(logits[node_type], data['test_idx'])
    test_y = tlx.gather(data['y'], data['test_idx'])
    test_acc = calculate_acc(test_logits, test_y, metrics)
    print("Test acc:  {:.4f}".format(test_acc))


if __name__ == '__main__':
    # parameters setting
    parser = argparse.ArgumentParser()
    parser.add_argument("--lr", type=float, default=0.005, help="learnin rate")
    parser.add_argument("--n_epoch", type=int, default=100, help="number of epoch")
    parser.add_argument("--hidden_dim", type=int, default=64, help="dimention of hidden layers")
    parser.add_argument("--l2_coef", type=float, default=1e-3, help="l2 loss coeficient")
    parser.add_argument("--heads", type=int, default=8, help="number of heads for stablization")
    parser.add_argument("--drop_rate", type=float, default=0.6, help="drop_rate")
    parser.add_argument("--gpu", type=int, default=0, help="gpu id")
    parser.add_argument("--dataset_path", type=str, default=r'', help="path to save dataset")
    parser.add_argument('--dataset', type=str, default='IMDB', help='dataset')
    parser.add_argument("--best_model_path", type=str, default=r'./', help="path to save best model")

    args = parser.parse_args()
    if args.gpu >= 0:
        tlx.set_device("GPU", args.gpu)
    else:
        tlx.set_device("CPU")

    main(args)
