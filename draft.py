import argparse
from tqdm import tqdm
#pytorch import
from Util import *
from GraphSAGEDiv import Model as Inducive_Model
from GraphSAGEDiv import Layer as Inducive_Layer
from HybridAttention import Model as Hybrid_Model
from MultihopAttention import Model as MultiHop_Model
from AMRNL import Model as AMRNL_Model
from CNTN import Model as CNTN_Model

from DataSet.dataset import clasifyDataSet, rankDataSet, my_clloect_fn_train, my_collect_fn_test, classify_collect_fn
from GraphSAGEDiv.DPP import *
from Metric.coverage_metric import *
from Metric.rank_metrics import ndcg_at_k, mean_average_precision_scikit, Accuracy, precision_at_k, mean_reciprocal_rank
import itertools
from Config import config_model




#grid search for paramter
from sklearn.model_selection import ParameterGrid
from Visualization.logger import Logger

info = {}
logger = Logger('./logs_map')
i_flag = 0
train_epoch_count = 0
eval_epoch_count = 0

def prepare_dataloaders(data, args, content_embed):
    # ========= Preparing DataLoader =========#
    train_question, test_question = train_test_split_len(data['question_count'])
    train_question += data['user_count']
    test_question += data['user_count']
    user_context = None
    content_embed = None
    if args.is_classification:

        train_loader = torch.utils.data.DataLoader(
            clasifyDataSet(G=data['G'],
                           args=args,
                        question_list=train_question,
                           user_context=user_context,
                           content=content_embed
                       ),
        num_workers=0,
        batch_size=args.batch_size,
        collate_fn=classify_collect_fn,
        shuffle=True
        )

        val_loader = torch.utils.data.DataLoader(
        clasifyDataSet(
            G=data['G'],
            args=args,
            question_list=test_question,
            user_context=user_context,
            content=content_embed,
        ),
        num_workers=0,
        batch_size=args.batch_size,
        collate_fn=classify_collect_fn,
        shuffle=True)
    else:
        train_loader = torch.utils.data.DataLoader(
            rankDataSet(
                G=data['G'],
                args=args,
                question_id_list=train_question,
                is_training=True,
                user_context=user_context,
                content = content_embed
            ),
            num_workers=0,
            batch_size=args.batch_size,
            shuffle=True,
            collate_fn= my_clloect_fn_train
        )

        val_loader = torch.utils.data.DataLoader(
            rankDataSet(
                G=data['G'],
                args=args,
                question_id_list=train_question,
                is_training=False,
                user_context=user_context,
                content=content_embed

            ),
            num_workers=0,
            batch_size=args.batch_size,
            shuffle=True,
            collate_fn=my_collect_fn_test

        )

    return train_loader, val_loader




def train_epoch(model, data, optimizer, args, train_epoch_count):
    model.train()
    loss_fn = nn.NLLLoss() if ~args.is_classification else Inducive_Layer.PairWiseHingeLoss(args.margin)

    for batch in tqdm(
        data, mininterval=2, desc=' --(training)--',leave=True
    ):
        if args.is_classification:
            q_iter, a_iter, u_iter, gt_iter, _ = map(lambda x: x.to(args.device), batch)
            args.batch_size = q_iter.shape[0]
            optimizer.zero_grad()
            result = model(q_iter, a_iter, u_iter)[0]
            loss = loss_fn(result, gt_iter)
            logger.scalar_summary("train_loss",loss.item(),1)
            loss.backward()
            optimizer.step()
        else:
            question_list, answer_pos_list, user_pos_list, score_pos_list, answer_neg_list, user_neg_list, score_neg_list, count_list = map(lambda x: x.to(args.device), batch)
            args.batch_size = question_list.shape[0]
            optimizer.zero_grad()
            score_pos = model(question_list, answer_pos_list, user_pos_list)
            score_neg = model(question_list, answer_neg_list, user_neg_list)
            t = 0
            result = 0
            for i in count_list:
                #torch.sum(regular_p + regular_n)
                result += loss_fn(score_pos[t: t + i], score_neg[t : t + i])
                t += i
            result.backward()
            optimizer.step()

    train_epoch_count += 1



    for tag, value in model.named_parameters():
        if value.grad is None:
            continue
        tag = tag.replace('.', '/')
        logger.histo_summary(tag, value.cpu().detach().numpy(), train_epoch_count)
        logger.histo_summary(tag + '/grad', value.grad.cpu().numpy(),train_epoch_count)



def eval_epoch(model, data, args, eval_epoch_count):
    model.eval()
    pred_label = []
    pred_score = []
    true_label = []
    label_score_order = []
    diversity_answer_recommendation = []
    val_answer_list = []
    question_list = []
    info_test = {}
    loss_fn = nn.NLLLoss() if args.is_classification else PairWiseHingeLoss(args.margin)
    loss = 0
    ndcg_loss = 0
    query_count = 0
    with torch.no_grad():
        for batch in tqdm(
            data, mininterval=2, desc="  ----(validation)----  ", leave=True
        ):
            if args.is_classification:
                q_val, a_val, u_val, gt_val, count = map(lambda x: x.to(args.device), batch)
                args.batch_size = gt_val.shape[0]
                score = model(q_val, a_val, u_val, True)
                loss += loss_fn(score, gt_val)
                # pred_label.append(tensorTonumpy(predict, args.cuda))
                true_label.append(tensorTonumpy(gt_val, args.cuda))

                count = tensorTonumpy(count, args.cuda)
                relevance_score = tensorTonumpy(score, args.cuda)
                # feature_matrix = tensorTonumpy(feature_matrix, args.cuda)
                pred_score.append(relevance_score)
                temp = 0
                question_list.append(tensorTonumpy(q_val, args.cuda))

                for i in count:
                    score_ = relevance_score[temp:temp + i]
                    # feature_matrix_ = feature_matrix[temp:temp+i]
                    #label order based on predicted score
                    label = true_label[-1][temp:temp+i]
                    sorted_index = np.argsort(-score_)
                    label = label[sorted_index]
                    label_score_order.append(label)

                    #coverage metric
                    #index -> [0-k]
                    # if args.use_dpp:
                    #     top_answer_index = diversity(feature_matrix_, score_, sorted_index, args.dpp_early_stop)
                    # else:
                    top_answer_index = list(range(i))
                    #id -> [10990, 12334, 1351]
                    top_answer_id = tensorTonumpy(a_val[temp:temp+i][top_answer_index], args.cuda)
                    val_answer = tensorTonumpy(a_val[temp:temp+i], args.cuda)
                    val_answer_list.append(val_answer)
                    diversity_answer_recommendation.append(top_answer_id)
                    temp += i
            else:
                q_val, a_val, u_val, gt_val, count = map(lambda x:x.to(args.device), batch)
                args.batch_size = gt_val.shape[0]
                relevance_score = model(q_val, a_val, u_val)
                count = tensorTonumpy(count, args.cuda)
                relevance_score = tensorTonumpy(relevance_score, args.cuda)
                temp = 0
                # feature_matrix = tensorTonumpy(feature_matrix, args.cuda)
                gt_val = tensorTonumpy(gt_val, args.cuda)
                true_label.append(gt_val)
                question_list.append(tensorTonumpy(q_val, args.cuda))
                a_val = tensorTonumpy(a_val, args.cuda)
                # assert len(feature_matrix) == np.sum(count), "length not equall"

                for i in count:
                    # diversity order => problem
                    # feature_matrix_ = feature_matrix[temp:temp+i]
                    score_ = relevance_score[temp:temp+i].reshape(-1,)
                    gt_val_ = gt_val[temp:temp+i]
                    a_val_ = a_val[temp:temp+i]
                    val_answer_list.append(a_val_)
                    sorted_index = np.argsort(-score_)
                    # ground truth sorted based on generated score order
                    score_sorted = gt_val_[sorted_index]
                    ndcg_loss += ndcg_at_k(score_sorted, args.ndcg_k)
                    query_count += 1

                    # coverage metric
                    # index -> [0-k]
                    # if args.use_dpp:
                    #     top_answer_index = diversity(feature_matrix_, score_, sorted_index,
                    #                                    args.dpp_early_stop)
                    # else:
                    top_answer_index = list(range(i))
                    # id -> [10990, 12334, 1351]
                    top_answer_id = a_val_[top_answer_index]
                    diversity_answer_recommendation.append(top_answer_id)
                    temp += i



    if ~args.is_classification:
        # pred_label_flatt = list(itertools.chain.from_iterable(pred_label))
        # true_label_flatt = list(itertools.chain.from_iterable(true_label))
        # score_list_flatt = list(itertools.chain.from_iterable(pred_score))

        # accuracy, zero_count, one_count = Accuracy(true_label_flatt, pred_label_flatt)
        mAP = mean_average_precision(true_label, pred_score)
        pat1 = precision_at_k(label_score_order, 1)
        mpr = mean_reciprocal_rank(label_score_order)

        # visualize the data
        info_test['eval_loss'] = loss.item()
        # info_test['eval_accuracy'] = accuracy
        info_test['zero_count'] = zero_count
        info_test['one_count'] = one_count
        info_test['mAP'] = mAP
        info_test['P@1'] = pat1
        info_test['mPR'] = mpr

        # print("[Info] Accuacy: {}; One Count {}".format(accuracy*1.0 / len(pred_label_flatt), len(pred_label_flatt), one_count))
        print("[Info] mAP: {}".format(mAP))
        eval_epoch_count += 1
    else:
        mean_ndcgg = ndcg_loss * 1.0 / query_count
        info_test['nDCGG'] = mean_ndcgg
        print("[INFO] Ranking Porblem nDCGG: {}".format(mean_ndcgg))

    #coverage metric



    for tag, value in info_test.items():
        logger.scalar_summary(tag, value, eval_epoch_count)

    return diversity_answer_recommendation, val_answer_list


    # diversity_recommendation(answer_id_dic,relevance_dic, content=content, early_stop=0.00001, topN=3)



def diversity_evaluation(diversity_answer_recommendation, content, topK, tfidf, lda):
    #init evaluate class
    tf_idf_score = 0
    lda_score = 0
    question_count = len(diversity_answer_recommendation)
    for candidate_answer_list in diversity_answer_recommendation:
        candidate_word_space = []
        temp_tfidf_score = 0
        temp_lda_score = 0
        for answer in candidate_answer_list:
            answer_content = content[answer].tolist()
            candidate_word_space += answer_content
        for top_answer in candidate_answer_list[:topK]:
            top_answer_content = content[top_answer]
            temp_tfidf_score += tfidf.simiarity(candidate_word_space, top_answer_content)
            temp_lda_score += lda.similarity(candidate_word_space, top_answer_content)


        tf_idf_score += temp_tfidf_score
        lda_score += temp_lda_score
    return (tf_idf_score * 1.0) / question_count, (lda_score * 1.0) / question_count


def grid_search(params_dic):
    '''
    :param params_dic: similar to {"conv_size":[0,1,2], "lstm_hiden_size":[1,2,3]}
    :return: iter {"conv_size":1, "lstm_hidden_size":1}
    '''
    grid_parameter = ParameterGrid(params_dic)
    parameter_list = []
    for params in grid_parameter:
        params_dic_result = {}
        for key in params_dic.keys():
            params_dic_result[key] = params[key]
        parameter_list.append(params_dic_result)
    return parameter_list



def train(args, train_data, val_data, user_count ,pre_trained_word2vec, G, content_embed, love_list_count, model_name):
    if model_name == "AMRNL":
        love_adj = ContentEmbed(torch.LongTensor(love_list_count[0]).to(args.device))
        love_len = ContentEmbed(torch.FloatTensor(love_list_count[1]).view(-1,1).to(args.device))
        model = AMRNL_Model.AMRNL(args, user_count, pre_trained_word2vec, content_embed, love_adj, love_len)
    elif model_name == "CNTN":
        model = CNTN_Model.CNTN(args, pre_trained_word2vec, content_embed, user_count)
    elif model_name == "Hybrid":
        model = Hybrid_Model.HybridAttentionModel(args, pre_trained_word2vec, content_embed,user_count)
    elif model_name == "Graph":
        adj, adj_edge, _ = Adjance(G, args.max_degree)
        adj = adj.to(args.device)
        adj_edge = adj_edge.to(args.device)
        model = Inducive_Model.InducieveLearningQA(args, user_count, adj, adj_edge, content_embed, pre_trained_word2vec)
    else:
        model = MultiHop_Model.MultihopAttention(args, pre_trained_word2vec, content_embed)

    print("Hello")
    content_numpy = content_embed.content_list.cpu().numpy() if args.cuda else content_embed.content_list.numpy()
    optimizer = torch.optim.Adam(model.parameters(), lr=args.lr)

    model.to(args.device)
    #load coverage model
    tfidf = TFIDFSimilar(content_numpy, args.cov_pretrain, args.cov_model_path)
    lda = LDAsimilarity(content_numpy, args.lda_topic, args.cov_pretrain, args.cov_model_path)
    if args.cov_pretrain is False:
        args.cov_pretrain = True
    info_val = {}

    for epoch_i in range(args.epoch):

        train_epoch(model, train_data, optimizer, args, epoch_i)

        diversity_answer_recommendation, _ = eval_epoch(model, val_data, args, eval_epoch_count)
        diversity_answer_recommendation = [item - user_count for item in diversity_answer_recommendation]
        tfidf_cov, lda_cov = diversity_evaluation(diversity_answer_recommendation, content_numpy, args.div_topK, tfidf, lda)

        info_val['tfidf_cov'] = tfidf_cov
        info_val['lda_cov'] = lda_cov
        print("[INFO] tfidf coverage {}, lda coverage {}".format(tfidf_cov, lda_cov))
        for tag, value in info_val.items():
            logger.scalar_summary(tag, value, eval_epoch_count)

        # test_loss, accuracy_test = eval_epoch(model, test_data, args, epoch_i)
        # print("[Info] Test Loss: {}, accuracy: {}".format(test_loss, accuracy_test))







def main():

    #===========Load DataSet=============#
    args = config_model
    print("cuda : {}".format(args.cuda))
    data = torch.load(args.data)
    word2ix = data['dict']
    G = data['G']
    user_count = data['user_count']
    love_list_count = []
    # if args.is_classification is False:
        # love_list_count = data['love_list_count']
    content = torch.LongTensor(data['content']).to(args.device)
    content_embed = ContentEmbed(content)
    train_data, val_data= prepare_dataloaders(data, args, content_embed)
    pre_trained_word2vec = loadEmbed(args.embed_fileName, args.embed_size, args.vocab_size, word2ix, args.DEBUG).to(args.device)
    model_name = args.model_name
    #grid search
    # if args.model == 1:
    paragram_dic = {"lstm_hidden_size":[128, 256],
                   "lstm_num_layers":[1,2,3,4],
                   "drop_out_lstm":[0.5],
                    "lr":[1e-4, 1e-3, 1e-2],
                    "margin":[0.1, 0.2, 0.3]
                    }
    pragram_list = grid_search(paragram_dic)
    for paragram in pragram_list:
        for key, value in paragram.items():
            print("Key: {}, Value: {}".format(key, value))
            setattr(args, key, value)
        train(args, train_data, val_data, user_count, pre_trained_word2vec, G, content_embed, love_list_count, model_name)
if __name__ == '__main__':
    main()
