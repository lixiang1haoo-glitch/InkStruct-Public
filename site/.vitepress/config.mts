import { defineConfig } from 'vitepress'

const repository = 'https://github.com/lixiang1haoo-glitch/InkStruct-Public'
const releases = `${repository}/releases`

export default defineConfig({
  lang: 'zh-CN',
  title: 'InkStruct 墨构',
  description: '从一笔一画开始，用自己的笔迹排一份文档。',
  base: '/InkStruct-Public/',
  head: [['link', { rel: 'icon', type: 'image/svg+xml', href: '/InkStruct-Public/inkstruct.svg' }]],
  lastUpdated: true,
  themeConfig: {
    logo: { src: '/inkstruct.svg', alt: 'InkStruct 墨构' },
    nav: [
      { text: '文档首页', link: '/' },
      { text: '上手教程', link: '/guide/first-document' },
      { text: '常见问题', link: '/guide/faq' },
      { text: '开发者文档', link: '/developers/', activeMatch: '^/developers/' },
      { text: '下载', link: releases },
    ],
    sidebar: [
      { text: '开始使用', items: [
        { text: '文档首页', link: '/' },
        { text: '做出第一份手写文档', link: '/guide/first-document' },
      ] },
      { text: '帮助与参考', items: [
        { text: '常见问题', link: '/guide/faq' },
        { text: '仓库速查页', link: `${repository}/blob/main/docs/USER_GUIDE.md` },
      ] },
      { text: '开发者文档', items: [
        { text: '开发者首页', link: '/developers/' },
        { text: 'CLI 与快速开始', link: '/developers/cli' },
        { text: '字体包 .inkfont', link: '/developers/inkfont' },
        { text: '项目文档 .inkdoc', link: '/developers/inkdoc' },
      ] },
    ],
    outline: { level: [2, 3], label: '本页大纲' },
    search: {
      provider: 'local',
      options: {
        translations: {
          button: { buttonText: '搜索文档', buttonAriaLabel: '搜索文档' },
          modal: {
            displayDetails: '显示结果详情',
            resetButtonTitle: '清空搜索',
            backButtonTitle: '返回',
            noResultsText: '没有找到相关内容',
            footer: { selectText: '选择', navigateText: '切换', closeText: '关闭' },
          },
        },
      },
    },
    socialLinks: [{ icon: 'github', link: repository }],
    editLink: { pattern: `${repository}/edit/main/site/:path`, text: '在 GitHub 上编辑此页' },
    lastUpdated: { text: '最后更新', formatOptions: { dateStyle: 'medium' } },
    docFooter: { prev: '上一页', next: '下一页' },
    sidebarMenuLabel: '文档目录',
    returnToTopLabel: '回到顶部',
    darkModeSwitchLabel: '外观',
    footer: { message: 'InkStruct 墨构 · 开源手写排版工具', copyright: '项目源码采用 MIT 许可' },
  },
})
