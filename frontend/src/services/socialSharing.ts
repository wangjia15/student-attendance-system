// Social Sharing Service with Rich Previews and Deep Linking
// Handles sharing across multiple platforms with fallbacks

import { createJoinLink, createSessionLink } from '../utils/deepLinking';

export interface ShareData {
  title: string;
  text: string;
  url: string;
  image?: string;
  hashtags?: string[];
}

export interface PlatformShareConfig {
  name: string;
  icon: string;
  color: string;
  urlTemplate: string;
  supportsImage: boolean;
  supportsHashtags: boolean;
  maxTextLength?: number;
}

export interface ClassShareData {
  classId: string;
  className: string;
  subject?: string;
  teacherName?: string;
  verificationCode?: string;
  qrCodeImage?: string;
  expiresAt?: Date;
}

// Platform configurations for social sharing
const PLATFORMS: Record<string, PlatformShareConfig> = {
  whatsapp: {
    name: 'WhatsApp',
    icon: '💬',
    color: '#25D366',
    urlTemplate: 'https://wa.me/?text={encodedText}',
    supportsImage: false,
    supportsHashtags: false,
    maxTextLength: 65536
  },
  
  telegram: {
    name: 'Telegram',
    icon: '✈️',
    color: '#0088CC',
    urlTemplate: 'https://t.me/share/url?url={encodedUrl}&text={encodedText}',
    supportsImage: false,
    supportsHashtags: true
  },
  
  twitter: {
    name: 'Twitter',
    icon: '🐦',
    color: '#1DA1F2',
    urlTemplate: 'https://twitter.com/intent/tweet?text={encodedText}&url={encodedUrl}&hashtags={hashtags}',
    supportsImage: false,
    supportsHashtags: true,
    maxTextLength: 280
  },
  
  facebook: {
    name: 'Facebook',
    icon: '👥',
    color: '#1877F2',
    urlTemplate: 'https://www.facebook.com/sharer/sharer.php?u={encodedUrl}&quote={encodedText}',
    supportsImage: true,
    supportsHashtags: false
  },
  
  linkedin: {
    name: 'LinkedIn',
    icon: '💼',
    color: '#0A66C2',
    urlTemplate: 'https://www.linkedin.com/sharing/share-offsite/?url={encodedUrl}&title={encodedTitle}&summary={encodedText}',
    supportsImage: true,
    supportsHashtags: false
  },
  
  email: {
    name: 'Email',
    icon: '📧',
    color: '#EA4335',
    urlTemplate: 'mailto:?subject={encodedTitle}&body={encodedText}%0A%0A{encodedUrl}',
    supportsImage: false,
    supportsHashtags: false
  },
  
  sms: {
    name: 'SMS',
    icon: '💬',
    color: '#34C759',
    urlTemplate: 'sms:?body={encodedText}%0A{encodedUrl}',
    supportsImage: false,
    supportsHashtags: false,
    maxTextLength: 160
  },
  
  copy: {
    name: 'Copy Link',
    icon: '📋',
    color: '#6C757D',
    urlTemplate: '',
    supportsImage: false,
    supportsHashtags: false
  }
};

export class SocialSharingService {
  
  // Check if native sharing is available
  isNativeSharingAvailable(): boolean {
    return 'share' in navigator && 'canShare' in navigator;
  }

  // Share using native Web Share API
  async shareNative(data: ShareData): Promise<boolean> {
    if (!this.isNativeSharingAvailable()) {
      return false;
    }

    try {
      const shareData: any = {
        title: data.title,
        text: data.text,
        url: data.url
      };

      // Check if data can be shared
      if ('canShare' in navigator && !navigator.canShare(shareData)) {
        console.warn('Data cannot be shared natively');
        return false;
      }

      await navigator.share(shareData);
      return true;
    } catch (error) {
      if (error instanceof Error && error.name === 'AbortError') {
        // User cancelled sharing
        console.log('Native sharing cancelled by user');
      } else {
        console.error('Native sharing failed:', error);
      }
      return false;
    }
  }

  // Share to specific platform
  shareToPlatform(platform: string, data: ShareData): void {
    const config = PLATFORMS[platform];
    if (!config) {
      console.error('Unsupported platform:', platform);
      return;
    }

    if (platform === 'copy') {
      this.copyToClipboard(data.url);
      return;
    }

    const shareUrl = this.buildPlatformUrl(config, data);
    
    // Open in new window/tab
    const popup = window.open(
      shareUrl,
      `share-${platform}`,
      'width=600,height=400,scrollbars=yes,resizable=yes'
    );

    if (!popup) {
      // Popup blocked, try direct navigation
      window.location.href = shareUrl;
    }
  }

  // Build platform-specific sharing URL
  private buildPlatformUrl(config: PlatformShareConfig, data: ShareData): string {
    let url = config.urlTemplate;
    let text = data.text;

    // Truncate text if platform has limits
    if (config.maxTextLength && text.length > config.maxTextLength) {
      text = text.substring(0, config.maxTextLength - 3) + '...';
    }

    // Build hashtags string
    const hashtags = config.supportsHashtags && data.hashtags ? 
      data.hashtags.join(',') : '';

    // Replace template variables
    url = url.replace('{encodedTitle}', encodeURIComponent(data.title));
    url = url.replace('{encodedText}', encodeURIComponent(text));
    url = url.replace('{encodedUrl}', encodeURIComponent(data.url));
    url = url.replace('{hashtags}', hashtags);

    return url;
  }

  // Copy to clipboard
  async copyToClipboard(text: string): Promise<boolean> {
    try {
      if (navigator.clipboard && window.isSecureContext) {
        await navigator.clipboard.writeText(text);
        return true;
      } else {
        // Fallback for older browsers
        const textArea = document.createElement('textarea');
        textArea.value = text;
        textArea.style.position = 'fixed';
        textArea.style.left = '-999999px';
        textArea.style.top = '-999999px';
        document.body.appendChild(textArea);
        textArea.focus();
        textArea.select();
        
        const result = document.execCommand('copy');
        textArea.remove();
        return result;
      }
    } catch (error) {
      console.error('Failed to copy to clipboard:', error);
      return false;
    }
  }

  // Generate sharing data for class session
  generateClassShareData(classData: ClassShareData): ShareData {
    const links = createJoinLink(classData.classId, classData.verificationCode);
    
    const title = `Join ${classData.className}${classData.subject ? ` - ${classData.subject}` : ''}`;
    
    let text = `You're invited to join the attendance session for "${classData.className}"`;
    
    if (classData.subject) {
      text += ` (${classData.subject})`;
    }
    
    if (classData.teacherName) {
      text += ` with ${classData.teacherName}`;
    }

    text += '\n\n📱 Join methods:';
    text += '\n• Scan QR code when shown';
    text += '\n• Click the link below';
    
    if (classData.verificationCode) {
      text += `\n• Enter code: ${classData.verificationCode}`;
    }

    if (classData.expiresAt) {
      const timeRemaining = Math.round((classData.expiresAt.getTime() - new Date().getTime()) / 60000);
      if (timeRemaining > 0) {
        text += `\n\n⏰ Session expires in ${timeRemaining} minutes`;
      }
    }

    return {
      title,
      text,
      url: links.universalUrl,
      image: classData.qrCodeImage,
      hashtags: ['attendance', 'education', classData.subject?.toLowerCase().replace(/\s+/g, '')].filter(Boolean)
    };
  }

  // Generate sharing data for session monitoring
  generateSessionShareData(classData: ClassShareData): ShareData {
    const links = createSessionLink(classData.classId);
    
    const title = `${classData.className} - Live Attendance`;
    
    let text = `View live attendance for "${classData.className}"`;
    
    if (classData.subject) {
      text += ` (${classData.subject})`;
    }
    
    text += '\n\n📊 See real-time:';
    text += '\n• Student join notifications';
    text += '\n• Participation statistics';
    text += '\n• Attendance metrics';

    return {
      title,
      text,
      url: links.universalUrl,
      hashtags: ['attendance', 'dashboard', 'education']
    };
  }

  // Generate rich sharing data for different contexts
  generateRichShareData(
    context: 'join' | 'monitor' | 'results',
    classData: ClassShareData,
    additionalData?: Record<string, any>
  ): ShareData {
    switch (context) {
      case 'join':
        return this.generateClassShareData(classData);
      
      case 'monitor':
        return this.generateSessionShareData(classData);
      
      case 'results':
        const links = createSessionLink(classData.classId);
        return {
          title: `${classData.className} - Attendance Results`,
          text: `View attendance results for "${classData.className}"\n\n📈 Session complete with ${additionalData?.totalStudents || 0} students participating.`,
          url: links.universalUrl,
          hashtags: ['attendance', 'results', 'education']
        };
      
      default:
        return this.generateClassShareData(classData);
    }
  }

  // Get available sharing platforms based on device/browser capabilities
  getAvailablePlatforms(): Array<{ id: string; config: PlatformShareConfig }> {
    const platforms = Object.entries(PLATFORMS).map(([id, config]) => ({ id, config }));
    
    // Filter out platforms based on device capabilities
    const isDesktop = !('ontouchstart' in window);
    const isMobile = 'ontouchstart' in window;
    
    return platforms.filter(({ id, config }) => {
      // SMS only on mobile
      if (id === 'sms' && isDesktop) return false;
      
      // Always show copy and email
      if (id === 'copy' || id === 'email') return true;
      
      return true;
    });
  }

  // Share with automatic platform detection and fallbacks
  async smartShare(data: ShareData, preferredPlatforms?: string[]): Promise<boolean> {
    // Try native sharing first on mobile
    if (this.isNativeSharingAvailable()) {
      const success = await this.shareNative(data);
      if (success) return true;
    }

    // Try preferred platforms
    if (preferredPlatforms && preferredPlatforms.length > 0) {
      const platform = preferredPlatforms[0];
      this.shareToPlatform(platform, data);
      return true;
    }

    // Fallback to copy link
    const success = await this.copyToClipboard(data.url);
    if (success) {
      console.log('Link copied to clipboard as fallback');
      return true;
    }

    return false;
  }

  // Generate meta tags for rich social media previews
  generateMetaTags(data: ShareData): string {
    const tags = [
      `<meta property="og:title" content="${data.title}" />`,
      `<meta property="og:description" content="${data.text}" />`,
      `<meta property="og:url" content="${data.url}" />`,
      `<meta property="og:type" content="website" />`,
      `<meta name="twitter:card" content="summary_large_image" />`,
      `<meta name="twitter:title" content="${data.title}" />`,
      `<meta name="twitter:description" content="${data.text}" />`,
      `<meta name="twitter:url" content="${data.url}" />`
    ];

    if (data.image) {
      tags.push(
        `<meta property="og:image" content="${data.image}" />`,
        `<meta name="twitter:image" content="${data.image}" />`
      );
    }

    return tags.join('\n');
  }
}

// Export singleton instance
export const socialSharingService = new SocialSharingService();

// Utility functions for common sharing scenarios
export const shareClassSession = async (classData: ClassShareData, platform?: string) => {
  const shareData = socialSharingService.generateClassShareData(classData);
  
  if (platform) {
    socialSharingService.shareToPlatform(platform, shareData);
  } else {
    return await socialSharingService.smartShare(shareData);
  }
};

export const shareSessionResults = async (classData: ClassShareData, results: any) => {
  const shareData = socialSharingService.generateRichShareData('results', classData, results);
  return await socialSharingService.smartShare(shareData);
};

export const copySessionLink = async (classId: string, code?: string) => {
  const links = createJoinLink(classId, code);
  return await socialSharingService.copyToClipboard(links.universalUrl);
};