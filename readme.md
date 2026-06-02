结构目录
pokemon-calculator/
├── agent.py
├── tools/
│   └── calc.mjs
├── package.json
├── requirements.txt
├── .env
└── README.md

# 1.环境 
pip install -r requirements.txt
npm install

# 2.模型配置
基于deepseek的api
在.env中配置：key/model_name/url

# 3.启动计算器
python agent.py

# 4.更新
node tools\build-name-maps.mjs