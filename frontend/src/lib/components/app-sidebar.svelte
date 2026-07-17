<script lang="ts">
	import * as Sidebar from '$lib/components/ui/sidebar/index.js';
	import { FontAwesomeIcon } from '@fortawesome/svelte-fontawesome';
	import { faGithub, faTelegram } from '@fortawesome/free-brands-svg-icons';
	import LayoutDashboardIcon from '@lucide/svelte/icons/layout-dashboard';
	import FilePenIcon from '@lucide/svelte/icons/file-pen';
	import CableIcon from '@lucide/svelte/icons/cable';
	import ServerIcon from '@lucide/svelte/icons/server';
	import CircleQuestionMarkIcon from '@lucide/svelte/icons/circle-question-mark';
	import SettingsIcon from '@lucide/svelte/icons/settings';
	import { AppRoutes } from '$lib/routes';
	import ButtonGroup from './ui/button-group/button-group.svelte';
	import Button from './ui/button/button.svelte';
	import ModeToggle from './mode-toggle.svelte';
	import LanguageSwitch from './language-switch.svelte';

	const items = [
		{
			title: 'Dashboard',
			url: AppRoutes.Dashboard(),
			icon: LayoutDashboardIcon
		},
		{
			title: 'Templates',
			url: AppRoutes.Templates(),
			icon: FilePenIcon
		},
		{
			title: 'Protocols',
			url: AppRoutes.Protocols(),
			icon: CableIcon
		},
		{
			title: 'Specs',
			url: '#',
			icon: CircleQuestionMarkIcon
		},
		{
			title: 'Nodes',
			url: '#',
			icon: ServerIcon
		},
		{
			title: 'Subscriptions',
			url: '#',
			icon: CircleQuestionMarkIcon
		},
		{
			title: 'Settings',
			url: '#',
			icon: SettingsIcon
		}
	];
</script>

<Sidebar.Root>
	<Sidebar.Header>
		<Sidebar.Menu>
			<Sidebar.MenuItem>
				<Sidebar.MenuButton size="lg">
					{#snippet child({ props })}
						<a href={AppRoutes.Dashboard()} {...props}>
							<div
								class="bg-primary text-sidebar-primary-foreground flex aspect-square size-8 items-center justify-center rounded-lg"
							>
								R
							</div>
							<div class="flex flex-col gap-0.5 leading-none">
								<span class="font-medium">ReinarPanel</span>
								<span class="">v1.0.0</span>
							</div>
						</a>
					{/snippet}
				</Sidebar.MenuButton>
			</Sidebar.MenuItem>
		</Sidebar.Menu>
	</Sidebar.Header>
	<Sidebar.Content>
		<Sidebar.Group>
			<Sidebar.GroupLabel>Panel</Sidebar.GroupLabel>
			<Sidebar.GroupContent>
				<Sidebar.Menu>
					{#each items as item (item.title)}
						<Sidebar.MenuItem>
							<Sidebar.MenuButton>
								{#snippet child({ props })}
									<a href={item.url} {...props}>
										<item.icon />
										<span>{item.title}</span>
									</a>
								{/snippet}
							</Sidebar.MenuButton>
						</Sidebar.MenuItem>
					{/each}
				</Sidebar.Menu>
			</Sidebar.GroupContent>
		</Sidebar.Group>
	</Sidebar.Content>
	<Sidebar.Footer>
		<div class="flex justify-between">
			<ButtonGroup>
				<Button variant="outline">
					<a href="https://github.com/ALXIReinar/Reinar-Panel">
						<!-- TODO: github api stargazers -->
						<FontAwesomeIcon icon={faGithub} />
					</a>
				</Button>
				<Button variant="outline">
					<a href="https://t.me/jazz_coding">
						<FontAwesomeIcon icon={faTelegram} />
					</a>
				</Button>
			</ButtonGroup>
			<ButtonGroup>
				<LanguageSwitch />
				<ModeToggle />
			</ButtonGroup>
		</div>
	</Sidebar.Footer>
</Sidebar.Root>
