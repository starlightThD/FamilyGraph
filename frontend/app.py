from flask import Flask, render_template

app = Flask(__name__)


@app.route('/')
def home():
    return render_template('home.html')


@app.route('/login')
def login():
    return render_template('login.html')


@app.route('/register')
def register():
    return render_template('register.html')


@app.route('/dashboard')
def dashboard():
    # TODO: 从后端接口获取当前登录用户可见的族谱统计信息
    stats = {
        'total_members': 128,
        'male_count': 70,
        'female_count': 58,
    }
    return render_template('dashboard.html', stats=stats)


@app.route('/family-trees')
def family_trees():
    # TODO: 从后端加载当前用户创建或被邀请的族谱列表
    trees = [
        {'id': 1, 'name': '张氏族谱', 'role': '创建者'},
        {'id': 2, 'name': '李氏支系', 'role': '协作者'},
    ]
    return render_template('family_trees.html', trees=trees)


@app.route('/tree-preview')
def tree_preview():
    # TODO: 根据选中的族谱和分支，动态返回树形结构数据
    sample_branch = {
        'name': '张祖德',
        'children': [
            {
                'name': '张明远',
                'children': [
                    {'name': '张文浩', 'children': []},
                    {'name': '张文静', 'children': []},
                ],
            },
            {
                'name': '张明华',
                'children': [
                    {'name': '张可欣', 'children': []},
                ],
            },
        ],
    }
    return render_template('tree_preview.html', sample_branch=sample_branch)


@app.route('/queries')
def queries():
    return render_template('queries.html')


if __name__ == '__main__':
    app.run(debug=True)
