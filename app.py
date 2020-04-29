from flask import Flask, request, jsonify, make_response
from flask_restful import Resource, Api
from flask_httpauth import HTTPBasicAuth
from jsonschema import validate
from pymongo import MongoClient
import json
import os
from dotenv import load_dotenv

load_dotenv(override=True)

MONGO_HOSTS = os.environ.get('MONGO_HOSTS', '127.0.0.1:27017')
MONGO_REPLICASET = os.environ.get('MONGO_REPLICASET', 'prometheus')
DEFAULT_USER = os.environ.get('DEFAULT_USER', 'prometheus')
DEFAULT_PASSWORD = os.environ.get('DEFAULT_PASSWORD', 'prometheus')

app = Flask(__name__)
api = Api(app)
auth = HTTPBasicAuth()

@auth.get_password
def get_password(username):
    if username == DEFAULT_USER:
        return DEFAULT_PASSWORD
    return None


@auth.error_handler
def unauthorized():
    # return 403 instead of 401 to prevent browsers from displaying the default
    # auth dialog
    return make_response(jsonify({'message': 'Unauthorized access'}), 403)


schema = {
     "type": "object",
     "properties": {
         "exporter": {"type": "string"},
         "target": {"type": "string"},
         "inventory_hostname": {"type": "string"},
         "labels": {"type": "object"}
     },
     "required": ["exporter", "target", "inventory_hostname", "labels"]
}

delete_schema = {
     "type": "object",
     "properties": {
         "zone": {"type": "string"},
         "exporter": {"type": "string"},
         "target": {"type": "string"},
         "inventory_hostname": {"type": "string"}
     },
     "required": ["zone", "exporter", "target", "inventory_hostname"]
}

# class IndexPage(Resource):
#     def get(self):
#         return {"message": "Need Web UI, Please add UI support https://github.com/narate/prom-file-sd"}


class PromTargets(Resource):
    decorators = [auth.login_required]

    def get(self):
        client = MongoClient([MONGO_HOSTS], replicaset=MONGO_REPLICASET)
        db = client.prom
        col = db.targets
        targets = []
        for target in col.find():
            targets.append({'exporter': target['exporter'], 'target': target['target'],
                            'labels': target.get('labels', {})})
        return {'targets': targets}
    
    def post(self):
        body = request.get_json()
        try:
            validate(body, schema)
        except:
            return {
                    'message': 'Input data invalid or miss some value, required: {}'.format(schema['required'])
            }, 400
        
        client = MongoClient([MONGO_HOSTS], replicaset=MONGO_REPLICASET)
        db = client.prom
        col = db.targets
        labels = body.get('labels', {})
        result = {
            'exporter': body['exporter'],
            'target': body['target'],
            'inventory_hostname': body['inventory_hostname'],
            'labels': labels
        }
        replace_proto = {
            'exporter': body['exporter'],
            'target': body['target'],
            'inventory_hostname': body['inventory_hostname']
        }
        find_proto = {
            'exporter': body['exporter'],
            'labels.zone': labels.get('zone')
        }
        metrics_path = labels.get('__metrics_path__')
        if metrics_path is not None:
            replace_proto['labels.__metrics_path__'] = metrics_path
        else:
            result['labels']['__metrics_path__'] = '/metrics'
        
        col.replace_one(replace_proto, result, True)
        with open('/prom/conf/' + body['exporter'] + '.json', 'w') as f:
            targets = []
            for target in col.find(find_proto, projection={'_id': False}):
                targets.append(
                    {
                        'targets': [target['target']],
                        'labels': target.get('labels', {})
                    }
                )
    
            f.write(json.dumps(targets, indent=2))
            f.flush()
            os.fsync(f.fileno())
        return {
            'status': 'created',
            'data': result
        }, 201

    def delete(self):
        body = request.get_json()
        try:
            validate(body, delete_schema)
        except:
            return {
                    'message': 'Input data invalid or miss some value, required: {}'.format(delete_schema['required'])
                }, 400
        
        client = MongoClient([MONGO_HOSTS], replicaset=MONGO_REPLICASET)
        db = client.prom
        col = db.targets
        delete_proto = {
            'exporter': body['exporter'],
            'labels.zone': body['zone'],
            'target': body['target'],
            'inventory_hostname': body['inventory_hostname']
        }
        find_proto = {
            'exporter': body['exporter'],
            'labels.zone': body['zone']
        }
        col.delete_one(delete_proto)
        with open('/prom/conf/' + body['exporter'] + '.json', 'w') as f:
            targets = []
            for target in col.find(find_proto, projection={'_id': False}):
                targets.append(
                    {
                        'targets': [target['target']],
                        'labels': target.get('labels', {})
                    }
                )
    
            f.write(json.dumps(targets, indent=2))
            f.flush()
            os.fsync(f.fileno())
        return None, 204

# api.add_resource(IndexPage, '/')


api.add_resource(PromTargets, '/targets')

if __name__ == '__main__':
    app.run(debug=True, host="0.0.0.0")
