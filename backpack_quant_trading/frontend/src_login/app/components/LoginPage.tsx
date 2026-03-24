import { useState } from 'react';
import { Button } from './ui/button';
import { Input } from './ui/input';
import { Tabs, TabsContent, TabsList, TabsTrigger } from './ui/tabs';

export function LoginPage() {
  const [loginUsername, setLoginUsername] = useState('');
  const [loginPassword, setLoginPassword] = useState('');
  const [registerUsername, setRegisterUsername] = useState('');
  const [registerEmail, setRegisterEmail] = useState('');
  const [registerPassword, setRegisterPassword] = useState('');
  const [registerConfirmPassword, setRegisterConfirmPassword] = useState('');

  const handleLogin = (e: React.FormEvent) => {
    e.preventDefault();
    console.log('Login:', { username: loginUsername, password: loginPassword });
  };

  const handleRegister = (e: React.FormEvent) => {
    e.preventDefault();
    console.log('Register:', { username: registerUsername, password: registerPassword });
  };

  return (
    <div className="min-h-screen w-full flex items-center justify-center bg-gradient-to-br from-blue-50 via-gray-50 to-blue-100 p-8">
      <div className="w-full max-w-xl">
        {/* Logo and Title */}
        <div className="text-center mb-10">
          <div className="inline-flex items-center justify-center w-16 h-16 bg-blue-600 rounded-2xl mb-6 shadow-lg">
            <svg 
              viewBox="0 0 24 24" 
              fill="none" 
              stroke="currentColor" 
              className="w-9 h-9 text-white"
            >
              <path 
                strokeLinecap="round" 
                strokeLinejoin="round" 
                strokeWidth={2} 
                d="M13 10V3L4 14h7v7l9-11h-7z" 
              />
            </svg>
          </div>
          <h1 className="text-gray-900 mb-2 text-3xl">沐龙量化</h1>
          <p className="text-base text-gray-500">Quantitative Trading Platform</p>
        </div>

        {/* Login/Register Card */}
        <div className="bg-white rounded-3xl shadow-xl p-10">
          <Tabs defaultValue="login" className="w-full">
            <TabsList className="grid w-full grid-cols-2 mb-8 h-12 bg-gray-100">
              <TabsTrigger value="login" className="text-base">登录</TabsTrigger>
              <TabsTrigger value="register" className="text-base">注册</TabsTrigger>
            </TabsList>

            {/* Login Tab */}
            <TabsContent value="login">
              <form onSubmit={handleLogin} className="space-y-5">
                <div>
                  <Input
                    type="text"
                    placeholder="用户名"
                    value={loginUsername}
                    onChange={(e) => setLoginUsername(e.target.value)}
                    className="h-12 bg-gray-50 border-0 text-base"
                  />
                </div>
                <div>
                  <Input
                    type="password"
                    placeholder="密码"
                    value={loginPassword}
                    onChange={(e) => setLoginPassword(e.target.value)}
                    className="h-12 bg-gray-50 border-0 text-base"
                  />
                </div>
                <div className="flex items-center justify-between text-sm">
                  <label className="flex items-center text-gray-600 cursor-pointer">
                    <input type="checkbox" className="mr-2 rounded w-4 h-4" />
                    记住我
                  </label>
                  <a href="#" className="text-blue-600 hover:text-blue-700 hover:underline">
                    忘记密码?
                  </a>
                </div>
                <Button 
                  type="submit" 
                  className="w-full h-12 bg-blue-600 hover:bg-blue-700 text-base mt-6"
                >
                  登录
                </Button>
              </form>
            </TabsContent>

            {/* Register Tab */}
            <TabsContent value="register">
              <form onSubmit={handleRegister} className="space-y-5">
                <div>
                  <Input
                    type="text"
                    placeholder="用户名"
                    value={registerUsername}
                    onChange={(e) => setRegisterUsername(e.target.value)}
                    className="h-12 bg-gray-50 border-0 text-base"
                  />
                </div>
                <div>
                  <Input
                    type="email"
                    placeholder="邮箱"
                    value={registerEmail}
                    onChange={(e) => setRegisterEmail(e.target.value)}
                    className="h-12 bg-gray-50 border-0 text-base"
                  />
                </div>
                <div>
                  <Input
                    type="password"
                    placeholder="密码"
                    value={registerPassword}
                    onChange={(e) => setRegisterPassword(e.target.value)}
                    className="h-12 bg-gray-50 border-0 text-base"
                  />
                </div>
                <div>
                  <Input
                    type="password"
                    placeholder="确认密码"
                    value={registerConfirmPassword}
                    onChange={(e) => setRegisterConfirmPassword(e.target.value)}
                    className="h-12 bg-gray-50 border-0 text-base"
                  />
                </div>
                <div className="text-sm text-gray-600">
                  <label className="flex items-start cursor-pointer">
                    <input type="checkbox" className="mr-2 mt-0.5 rounded w-4 h-4" />
                    <span>我同意<a href="#" className="text-blue-600 hover:text-blue-700 hover:underline ml-1 mr-1">服务条款</a>和<a href="#" className="text-blue-600 hover:text-blue-700 hover:underline ml-1">隐私政策</a></span>
                  </label>
                </div>
                <Button 
                  type="submit" 
                  className="w-full h-12 bg-blue-600 hover:bg-blue-700 text-base mt-6"
                >
                  注册
                </Button>
              </form>
            </TabsContent>
          </Tabs>
        </div>

        {/* Footer */}
        <div className="text-center mt-8 text-sm text-gray-500">
          © 2024 沐龙量化. All rights reserved.
        </div>
      </div>
    </div>
  );
}