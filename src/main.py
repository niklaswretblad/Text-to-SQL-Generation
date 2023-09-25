
from db_interface import *
from utils import load_json
import os

QUESTIONS_PATH = os.path.abspath(os.path.join(os.path.dirname( __file__ ), '..', 'data/questions.json'))

ACCEPTED_DATABASES = [
    'car_retails',
    'financial',
    # 'retail_world',
    #'retails'
]

def main():
    api_key = os.environ.get('OPENAI_API_KEY')
    if api_key is None:
        raise ValueError("OPENAI_API_KEY environment variable is not set.")

    questions = load_json(QUESTIONS_PATH)
    questions = [question for question in questions if question['db_id'] in ACCEPTED_DATABASES]
    db_loader = DBLoader(ACCEPTED_DATABASES)

    score = 0
    total_questions = len(questions)
    for i, row in enumerate(questions):
        if row['db_id'] in ACCEPTED_DATABASES:
            golden_sql = row['SQL']
            db_id = row['db_id']
            
            res = db_loader.execute_query(golden_sql, golden_sql, db_id)
            score += res

            print("Percentage done: ", round(i / total_questions * 100, 2), "% Domain: ", db_id)

    print("accuracy: ", score / len(questions))

if __name__ == "__main__":
    main()