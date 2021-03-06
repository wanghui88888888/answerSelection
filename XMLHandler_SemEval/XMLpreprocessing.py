"""This module provides preprocessing routines for SemEval Task 3, Subtask B datasets."""

from lxml import etree
import os
def parse(xmlfile, content_id, user_dic, user_context, category_dic):
    # xmlfile="/home/yichuan/course/induceiveAnswer/data/v3.2/train/SemEval2016-Task3-CQA-QL-train-part1-subtaskA.xml"
    tree = etree.parse(xmlfile)
    th = content_id
    good = 1
    bad = 0
    content = []
    question_answer_user_label_cate = []
    for thread in tree.findall("Thread"):
        q_Id_formal = thread.find("RelQuestion").attrib["RELQ_ID"]
        q_Id = content_id
        category = thread.find('RelQuestion').attrib["RELQ_CATEGORY"]
        content_id += 1
        # Store question content
        # TODO: handle non text
        # if thread.find("RelQuestion/RelQBody") is None:
        #     continue

        if thread.find("RelQuestion/RelQClean") is not None:
            q_content = thread.find("RelQuestion/RelQClean").text
        elif thread.find("RelQuestion/RelQBody").text is not None:
            q_content = thread.find("RelQuestion/RelQBody").text
        else:
            q_content = thread.find("RelQuestion/RelQSubject").text

        if q_content is None:
            print(thread.attrib)
            print("q_content {}".format(q_content))
            print(thread.find("RelQuestion/RelQSubject").text)
        assert q_content is not None and len(q_content) > 0, "[ERROR] question content is emtpy"


        content.append(q_content)
        if category not in category_dic:
            category_dic[category] = len(category_dic)
        category_index = category_dic[category]
        for relcomment in (thread.findall("RelComment")):

            a_Id_formal = relcomment.attrib["RELC_ID"]
            test_q_id = a_Id_formal.split("_")
            a_Id = content_id


            if len(test_q_id) == 2:
                test_q_id = test_q_id[0]
            else:
                test_q_id = test_q_id[0] + "_" + test_q_id[1]
            assert q_Id_formal == test_q_id, "[ERROR] question id {} conliction {} in {}".format(q_Id_formal, test_q_id, xmlfile)
            a_user_Id = relcomment.attrib["RELC_USERID"]
            a_user_name = relcomment.attrib["RELC_USERNAME"]

            #ATTENTION: remove anonymous
            if a_user_Id == "U2" and a_user_name == "anonymous":
                continue
            content_id += 1

            if a_user_Id not in user_dic:
                user_dic[a_user_Id] = len(user_dic)
            a_user_Id = user_dic[a_user_Id]

            if a_user_Id not in user_context:
                user_context[a_user_Id] = set([a_Id])
            else:
                user_context[a_user_Id].add(a_Id)

            label = good if relcomment.attrib["RELC_RELEVANCE2RELQ"] == 'Good' else bad

            if relcomment.find("RelCClean") is not None:
                answer_content = relcomment.find("RelCClean").text
            elif relcomment.find("RelCText") is not None:
                answer_content = relcomment.find("RelCText").text
            else:
                try:
                    answer_content = relcomment.find("RelCBody").text
                except:
                    print("{} {} {} {}".format(q_Id, a_Id, a_user_Id, xmlfile))
                    exit()

            assert answer_content is not None and len(answer_content) > 0, "[ERROR] Answer content is empty"
            content.append(answer_content)
            # user here is answerer
            question_answer_user_label_cate.append([q_Id, a_Id, a_user_Id, label, category_index])


    assert content_id - th == len(content), "add data problem"
    assert len(content) > 0, "[ERROR] content data in {} is empty".format(xmlfile)
    return content, question_answer_user_label_cate, user_dic, content_id, user_context, category_dic









