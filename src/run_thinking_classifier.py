import os
from datasets import get_dataset
from langchain.chat_models import ChatOpenAI
from langchain.prompts import PromptTemplate
from langchain.chains import LLMChain
from langchain.callbacks import get_openai_callback
from utils.timer import Timer
import logging

from config import api_key, load_config
import wandb
import langchain
# langchain.verbose = True

# If you don't want your script to sync to the cloud
# os.environ["WANDB_MODE"] = "offline"

LOGICAL_REASONING_PROMPT = """
You are a text-to-SQL expert able to identify poorly formulated questions in natural language that cannot correctly be converted into a SQL query.
The dataset used is consisting of questions and their corresponding golden SQL queries. You will be given the database schema of the database corresponding to the question.
Furthermore, you will also be given a hint that provides additional information that is needed to correctly convert the question and interpret the database schema.
However, some of the questions in the data are poorly formulated or contain errors. 

Below is a classification scheme for the questions that are to be converted into SQL queries. 

0 = Correct question. May still contain minor errors in language or minor ambiguities that do not affect the interpretation and generation of the SQL query
1 = The question is  either unclear, ambiguous, unspecific or contain grammatical errors that surely is going to affect the interpretation and generation of the SQL query
1 = The question is wrongly formulated when considering the structure of the database schema. The information that the question is asking for is not possible to accurately retrieve from the database.
1 = The question is unspecific in which columns that are to be returned. The question is not asking for a specific column, but asks generally about a table in the database.

Here are some examples of questions that would be classified with 0 and an explanation of why:

Example 1: List the id of the customer who made the transaction id : 3682978
Explanation: Clear and correct question.

Example 2: What is the name of the district that has the largest amount of female clients?
Explanation: Specific and  correct question.

Example 3: What is the disposition id(s) of the oldest client in the Prague region?
Explanation: The question is open for disposition ids which is correct when considering the sql-schema.

Example 4: What was the average number of withdrawal transactions conducted by female clients from the Prague region during the year 1998?
Explanation: Clear and correct question.

Here are some examples of questions that would be classified with 1 and an explanation of why:

Example 1: List the customer who made the transaction id 3682978
Explanation: The question is unspecific in which columns that are to be returned. It asks to list the customers, but does not specify which columns that are to be returned from the client table. 

Example 2: Which district has the largest amount of female clients?
Explanation: The question is unspecific in which columns that are to be returned. It asks "which district", but does not specify which columns that are to be returned from the district table. 

Example 3: What is the disposition id of the oldest client in the Prague region?
Explanation: The question is wrongly formulated when considering the structure of the database schema. There can be multiple disposition ids for a client, 
since a client can have multiple accounts. The question is not asking for a specific disposition id, but asks generally about a client.

Example 4: What is the average amount of transactions done in the year of 1998 ?
Explanation: Is unclear, ambiguous, unspecific or contain grammatical errors that surely is going to affect the interpretation and generation of the SQL query.

Database schema: 

{database_schema}

Hint: {evidence}

What do you think about the following question? Remember that some questions might contain errors, but would still be good enough to convert into a SQL query. 
Also please assume that all dates, values, names and numbers in the questions are in the correct format and valid against the databse so you do not need to reason about them.

Question: {question}
"""

QUESTION_CLASSIFICATION_PROMPT = """
You are a text-to-SQL expert able to identify poorly formulated questions in natural language.
The dataset used is consisting of questions and their corresponding golden SQL queries. You will be given the database schema of the database corresponding to the question and query.
Furthermore, you will also be given a hint that provides additional information that is needed to correctly convert the question and interpret the database schema.  
However, some of the questions in the data are poorly formulated or contain errors. 

Below is a classification scheme for the questions that are to be converted into SQL queries. 

0 = Correct question. May still contain minor errors in language or minor ambiguities that do not affect the interpretation and generation of the SQL query
1 = Is unclear, ambiguous, unspecific or contain grammatical errors that surely is going to affect the interpretation and generation of the SQL query
1 = The question is wrongly formulated when considering the structure of the database schema. The information that the question is asking for is not possible to accurately retrieve from the database.
1 = The question is unspecific in which columns that are to be returned. The question is not asking for a specific column, but asks generally about a table in the database.

Here are some examples of questions that would be classified with 0 and an explanation of why:

Example 1: List the id of the customer who made the transaction id : 3682978
Explanation: Clear and correct question.

Example 2: What is the name of the district that has the largest amount of female clients?
Explanation: Specific and  correct question.

Example 3: What is the disposition id(s) of the oldest client in the Prague region?
Explanation: The question is open for disposition ids which is correct when considering the sql-schema.

Example 4: What was the average number of withdrawal transactions conducted by female clients from the Prague region during the year 1998?
Explanation: Clear and correct question.

Here are some examples of questions that would be classified with 1 and an explanation of why:

Example 1: List the customer who made the transaction id 3682978
Explanation: The question is unspecific in which columns that are to be returned. It asks to list the customers, but does not specify which columns that are to be returned from the client table. 

Example 2: Which district has the largest amount of female clients?
Explanation: The question is unspecific in which columns that are to be returned. It asks "which district", but does not specify which columns that are to be returned from the district table. 

Example 3: What is the disposition id of the oldest client in the Prague region?
Explanation: The question is wrongly formulated when considering the structure of the database schema. There can be multiple disposition ids for a client, 
since a client can have multiple accounts. The question is not asking for a specific disposition id, but asks generally about a client.

Example 4: What is the average amount of transactions done in the year of 1998 ?
Explanation: Is unclear, ambiguous, unspecific or contain grammatical errors that surely is going to affect the interpretation and generation of the SQL query.

Database schema: 

{database_schema}

Hint: {evidence}

Also please assume that all dates, values, names and numbers in the questions are in the correct format and valid against the databse so you do not need to reason about them.

In a previous question I asked you to reason about the quality of the question and if the question would be valid to generate a SQL query from. 
Based on the question and your reasoning in the previous step, please classify the question as either good or bad, where

0 = Correct question that can successfully be converted to an accurate SQL query without any changes
1 = Faulty question that will not successfully be able to be converted to an accurate SQL query without changes

Question: {question}

Your reasoning: {thoughts}

Do not return anything except your classification as a sole number. Do not, under any circumstance, return any corresponding text or explanations.
"""


# LOGICAL_REASONING_PROMPT = """
# I am doing text-to-SQL generation, but some of the questions in my dataset are bad.
# You are a text-to-SQL expert able to identify questions that are formulated poorly or which contain errors. 
# The questions can also map poorly to the corresponding database schema, or in other words a valid SQL query might not exist for the question. 

# Below are the database schema of the database. 

# Database schema:

# {database_schema}

# Below is a hint which provides information that might be necessary to correctly convert the question into a SQL query.

# Hint: {evidence}

# Note that some questions might contain errors, but would still be good enough to convert into a SQL query. 
# Also please assume that all dates, values, names and numbers in the questions are correct so you do not need to reason about them.
# Thirdly note that the main goal is to get a very high recall on the classifications. 
# So please be harsh in your reasoning, and if in doubt whether the question is considered good or bad, be pessimistic and pick bad.

# What do you think about the following question? Can it succesfully be converted into a SQL query without any changes to the original question? 

# Question: {question}
# """

# QUESTION_CLASSIFICATION_PROMPT = """
# I am doing text-to-SQL generation, but some of the questions in my dataset are bad.
# You are a text-to-SQL expert able to identify questions that are formulated poorly or which contain errors. 
# The questions can also map poorly to the corresponding database schema, or in other words a valid SQL query might not exist for the question.

# In a previous prompt I asked you to reason about whether a given question was good or bad. Depending on your reasoning, please classify the question as either: 

# 0 = The question is able to be accurately converted into a SQL query without any changes to the question. 
# 1 = The question is invalid or needs to be changed or reformulated in order to be accurately converted into a SQL query

# The question: {question}

# Your thoughts: {thoughts}

# In your answer DO NOT return anything else than your classification mark as a sole number. Do not return any corresponding text or explanations. 
# """


# """
# I am doing text-to-SQL generation, but some of the questions in my dataset are bad. 
# You are a text-to-SQL expert able to identify questions that are formulated poorly or that contain errors. 
# Note that some questions might contain errors, but would still be good enough to convert into a SQL query. 

# In a previous question I asked you to reason about the quality of the question and if the question would be valid to generate a SQL query from. 
# Based on the question and your reasoning in the previous step, please classify the question as either good or bad, where

# 0 = The question is correct. May still contain minor errors in language or minor ambiguities that do not affect the interpretation and generation of the SQL query
# 1 = The question is either unclear, ambiguous, unspecific or contain grammatical errors that surely is going to affect the interpretation and generation of the SQL query
# 1 = The question is wrongly formulated when considering the structure of the database schema. The information that the question is asking for is not possible to accurately retrieve from the database.
# 1 = The question is unspecific in which columns that are to be returned. The question is not asking for a specific column, but asks generally about a table in the database.

# Question: {question}

# Your reasoning: {thoughts}

# Do not return anything except your classification as a sole number. Do not, under any circumstance, return any corresponding text or explanations.
# """

class Classifier():
    total_tokens = 0
    prompt_tokens = 0 
    total_cost = 0
    completion_tokens = 0
    last_call_execution_time = 0
    total_call_execution_time = 0

    def __init__(self, llm):        
        self.llm = llm

        self.reasoning_template = LOGICAL_REASONING_PROMPT
        prompt = PromptTemplate(            
            input_variables=["question", "database_schema", "evidence"],
            template=self.reasoning_template,
        )
        self.reasoning_chain = LLMChain(llm=llm, prompt=prompt)

        self.classification_template = QUESTION_CLASSIFICATION_PROMPT
        prompt = PromptTemplate(            
            input_variables=["question", "thoughts", "database_schema", "evidence"],
            # input_variables=["question", "thoughts"],
            template=self.classification_template,
        )
        self.classification_chain = LLMChain(llm=llm, prompt=prompt)


    def classify_question(self, question, schema, evidence):
        with get_openai_callback() as cb:
            with Timer() as t:
                response = self.reasoning_chain.run({
                    'database_schema': schema,
                    'evidence': evidence,
                    'question': question
                })

            logging.info(f"OpenAI API execution time: {t.elapsed_time:.2f}")
            
            self.last_call_execution_time = t.elapsed_time
            self.total_call_execution_time += t.elapsed_time
            self.total_tokens += cb.total_tokens
            self.prompt_tokens += cb.prompt_tokens
            self.total_cost += cb.total_cost
            self.completion_tokens += cb.completion_tokens

            with Timer() as t:
                response = self.classification_chain.run({
                    'question': question,
                    'thoughts': response,
                    'database_schema': schema,
                    'evidence': evidence
                })

            logging.info(f"OpenAI API execution time: {t.elapsed_time:.2f}")
            
            self.last_call_execution_time = t.elapsed_time
            self.total_call_execution_time += t.elapsed_time
            self.total_tokens += cb.total_tokens
            self.prompt_tokens += cb.prompt_tokens
            self.total_cost += cb.total_cost
            self.completion_tokens += cb.completion_tokens

            return response


accepted_faults = [1, 2, 3]

def main():
    config = load_config("classifier_config.yaml")

    wandb.init(
        project=config.project,
        config=config,
        name=config.current_experiment,
        entity=config.entity
    )

    artifact = wandb.Artifact('query_results', type='dataset')
    table = wandb.Table(columns=["Question", "Classified_quality", "Difficulty"]) ## Är det något mer vi vill ha med här?

    llm = ChatOpenAI(
        openai_api_key=api_key, 
        model_name=config.llm_settings.model,
        temperature=config.llm_settings.temperature,
        request_timeout=config.llm_settings.request_timeout
    )

    dataset = get_dataset("BIRDCorrectedFinancialGoldAnnotated")
    classifier = Classifier(llm)

    no_data_points = dataset.get_number_of_data_points()

    tp = 0
    fp = 0
    tn = 0
    fn = 0
    
    for i in range(no_data_points):
        data_point = dataset.get_data_point(i)
        evidence = data_point['evidence']
        db_id = data_point['db_id']            
        question = data_point['question']
        difficulty = data_point['difficulty'] if 'difficulty' in data_point else ""
        annotated_question_quality = data_point["annotation"]
        
        sql_schema = dataset.get_bird_table_info(db_id)

        classified_quality = classifier.classify_question(question, sql_schema, evidence)

        annotated_question_qualities = set(annotated_question_quality)
        if classified_quality.isdigit() and int(classified_quality) == 1:            
            if any(element in annotated_question_qualities for element in accepted_faults):
                tp += 1
            else:
                fp += 1
        elif classified_quality.isdigit() and int(classified_quality) == 0:
            if any(element in annotated_question_qualities for element in accepted_faults):
                fn += 1
            else:
                tn += 1
        
        table.add_data(question, classified_quality, difficulty)
        wandb.log({                      
            "total_tokens": classifier.total_tokens,
            "prompt_tokens": classifier.prompt_tokens,
            "completion_tokens": classifier.completion_tokens,
            "total_cost": classifier.total_cost,
            "openAPI_call_execution_time": classifier.last_call_execution_time,
        }, step=i+1)
    
        print("Predicted quality: ", classified_quality, " Annotated quality: ", " ".join(map(str, annotated_question_quality)))
        
    precision = tp / (tp + fp)
    recall = tp / (tp + fn)
    f1 = 2 * ((precision * recall) / (precision + recall))
    accuracy = (tp + tn) / (tp + tn + fp + fn)

    wandb.run.summary['accuracy']                           = accuracy
    wandb.run.summary['precision']                          = precision
    wandb.run.summary['recall']                             = recall
    wandb.run.summary['f1']                                 = f1
    wandb.run.summary["total_tokens"]                       = classifier.total_tokens
    wandb.run.summary["prompt_tokens"]                      = classifier.prompt_tokens
    wandb.run.summary["completion_tokens"]                  = classifier.completion_tokens
    wandb.run.summary["total_cost"]                         = classifier.total_cost
    wandb.run.summary['total_predicted_execution_time']     = dataset.total_predicted_execution_time
    wandb.run.summary['total_openAPI_execution_time']       = classifier.total_call_execution_time

    artifact.add(table, "query_results")
    wandb.log_artifact(artifact)

    artifact_code = wandb.Artifact('code', type='code')
    artifact_code.add_file("src/run_classifier.py")
    wandb.log_artifact(artifact_code)

    wandb.finish()



if __name__ == "__main__":
    main()